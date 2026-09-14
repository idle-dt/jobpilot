"""Tests for the service layer extracted from the route handlers."""

import sqlite3

from jobpilot.services.classification_service import ClassificationService
from jobpilot.services.inbox_service import (
    DEFAULT_SORT,
    InboxService,
    sort_signals,
)
from jobpilot.services.ml_export_service import MLExportService
from jobpilot.services.settings_service import SettingsService
from jobpilot.services.tracker_service import (
    TrackerService,
    _parse_tracker_sort,
    canonical_tracker_sort,
)
from jobpilot.storage.models import Application, ExtractedSignal
from jobpilot.storage.repository import Repository


def _insert_review_job(
    db_conn: sqlite3.Connection, title: str, score: float,
    classification: str = "worth_checking",
) -> None:
    """Insert an unlabeled scraped job that qualifies for the review queue."""
    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url, score, classification) "
        "VALUES (?,?,?,?,?)",
        ("linkedin", title, f"https://linkedin.com/jobs/view/{title}", score,
         classification),
    )
    db_conn.commit()


# --- InboxService ---

def test_sort_signals_orders_by_priority() -> None:
    """tech_stack sorts before platform; unknown types fall to the end."""
    signals = [
        ExtractedSignal(id=None, email_id="e", signal_type="platform", signal_value="x"),
        ExtractedSignal(id=None, email_id="e", signal_type="tech_stack", signal_value="y"),
        ExtractedSignal(id=None, email_id="e", signal_type="mystery", signal_value="z"),
    ]
    ordered = [s.signal_type for s in sort_signals(signals)]
    assert ordered == ["tech_stack", "platform", "mystery"]


def test_build_review_queue_sorts_by_score(repo: Repository, db_conn) -> None:
    """score_desc puts the highest-scored item first; score_asc reverses it."""
    _insert_review_job(db_conn, "low", 0.2)
    _insert_review_job(db_conn, "high", 0.9)
    service = InboxService(repo)

    desc = service.build_review_queue("score_desc")
    asc = service.build_review_queue("score_asc")

    assert [i["obj"].title for i in desc] == ["high", "low"]
    assert [i["obj"].title for i in asc] == ["low", "high"]


def test_build_review_queue_invalid_sort_falls_back(repo: Repository, db_conn) -> None:
    """An unknown sort key is treated as the default (score_desc)."""
    _insert_review_job(db_conn, "low", 0.2)
    _insert_review_job(db_conn, "high", 0.9)
    service = InboxService(repo)

    assert service.build_review_queue("bogus") == service.build_review_queue(DEFAULT_SORT)


def test_build_review_queue_noise_flag_false_without_predictions(
    repo: Repository, db_conn,
) -> None:
    """With no ML predictions, no item is flagged as noise."""
    _insert_review_job(db_conn, "job", 0.5)
    items = InboxService(repo).build_review_queue()
    assert items and all(item["noise_flag"] is False for item in items)


def test_count_review_totals_arithmetic(repo: Repository, db_conn) -> None:
    """skip_count is the review total minus the worth_checking count."""
    _insert_review_job(db_conn, "wc", 0.8, classification="worth_checking")
    _insert_review_job(db_conn, "noise", 0.1, classification="not_a_job")
    total, worth_checking, skip = InboxService(repo).count_review_totals()
    assert total == 2
    assert worth_checking == 1
    assert skip == 1


# --- SettingsService ---

def test_settings_context_has_expected_keys(repo: Repository) -> None:
    """build_context returns every key the settings template consumes."""
    context = SettingsService(repo).build_context()
    expected = {
        "sync_days", "score_threshold", "prefs", "salary_currency",
        "salary_min", "salary_max", "arbeitnow_enabled", "arbeitnow_visa_only",
        "domain_list", "browser_sessions",
    }
    assert expected <= set(context)


def test_settings_domain_list_dedups_and_flags_active(repo: Repository) -> None:
    """A domain added as a preference appears once and is marked active."""
    repo.insert_preference("monitored_domain", "linkedin.com")  # also a known domain
    domain_list = SettingsService(repo).build_context()["domain_list"]

    linkedin = [d for d in domain_list if d["domain"] == "linkedin.com"]
    assert len(linkedin) == 1  # not duplicated despite being known + a preference
    assert linkedin[0]["active"] is True


# --- MLExportService ---

def test_build_export_shape_on_empty_db(repo: Repository) -> None:
    """An export with no models still has the full top-level structure."""
    export = MLExportService(repo).build_export("scoring")
    assert set(export) == {
        "exported_at", "model_type", "training_data", "algorithms",
        "predictions", "disagreements",
    }
    assert export["model_type"] == "scoring"
    assert export["algorithms"] == {}
    assert export["training_data"]["samples"] == []


def test_build_prediction_entry_detects_disagreement() -> None:
    """A model whose prediction differs from the user label is flagged disagreeing."""
    item = {
        "item_type": "email",
        "item_id": "x",
        "title": "Backend Engineer",
        "user_label": "worth_checking",
        "raw_score": 0.5,
        "predictions": {
            "LR": {"prediction": "skip", "probability": 0.9},
            "RF": {"prediction": "worth_checking", "probability": 0.8},
        },
    }
    entry, disagree = MLExportService._build_prediction_entry(item)
    assert set(entry["ml_predictions"]) == {"LR", "RF"}
    assert disagree == ["LR"]


# --- TrackerService sorting ---

def _app(
    role: str, *, status: str = "applied", applied_at: str | None = None,
) -> Application:
    """Build an Application with sensible defaults for sort tests."""
    return Application(
        id=None, company="Acme", role_title=role,
        status=status, applied_at=applied_at,
    )


def test_parse_tracker_sort_valid_and_invalid() -> None:
    """Only applied_asc/desc parse; everything else falls back to the status default."""
    assert _parse_tracker_sort("status") == ("status", "asc")
    assert _parse_tracker_sort("applied_asc") == ("applied", "asc")
    assert _parse_tracker_sort("applied_desc") == ("applied", "desc")
    # Other columns are not sortable — they fall back to the pipeline-rank default.
    assert _parse_tracker_sort("company_asc") == ("status", "asc")
    assert _parse_tracker_sort("INVALID") == ("status", "asc")
    assert _parse_tracker_sort("") == ("status", "asc")


def test_canonical_tracker_sort_normalizes_untrusted_input() -> None:
    """Junk and non-applied columns canonicalize to the default; applied passes through."""
    assert canonical_tracker_sort("applied_asc") == "applied_asc"
    assert canonical_tracker_sort("applied_desc") == "applied_desc"
    assert canonical_tracker_sort("company_asc") == "status"
    assert canonical_tracker_sort('"><script>') == "status"
    assert canonical_tracker_sort("") == "status"


def test_sort_applications_applied_asc_nulls_last() -> None:
    """applied_asc: oldest first, rows with no applied_at sink to the bottom."""
    apps = [
        _app("new", applied_at="2026-03-01T00:00:00"),
        _app("none", applied_at=None),
        _app("old", applied_at="2026-01-01T00:00:00"),
    ]
    ordered = TrackerService(None)._sort_applications(apps, "applied_asc")
    assert [a.role_title for a in ordered] == ["old", "new", "none"]


def test_sort_applications_applied_desc_nulls_still_last() -> None:
    """applied_desc: newest first, but null applied_at still sorts last."""
    apps = [
        _app("old", applied_at="2026-01-01T00:00:00"),
        _app("none", applied_at=None),
        _app("new", applied_at="2026-03-01T00:00:00"),
    ]
    ordered = TrackerService(None)._sort_applications(apps, "applied_desc")
    assert [a.role_title for a in ordered] == ["new", "old", "none"]


def test_sort_applications_applied_ties_break_by_pipeline_rank() -> None:
    """Rows with identical applied_at fall back to pipeline rank as the tiebreaker."""
    same = "2026-02-01T00:00:00"
    apps = [
        _app("saved-row", status="saved", applied_at=same),
        _app("offer-row", status="offer", applied_at=same),
    ]
    ordered = TrackerService(None)._sort_applications(apps, "applied_asc")
    assert [a.role_title for a in ordered] == ["offer-row", "saved-row"]


def test_sort_applications_default_is_pipeline_rank() -> None:
    """sort=status orders by pipeline rank (offer before saved before withdrawn)."""
    apps = [
        _app("c", status="withdrawn"),
        _app("a", status="offer"),
        _app("b", status="saved"),
    ]
    ordered = TrackerService(None)._sort_applications(apps, "status")
    assert [a.status for a in ordered] == ["offer", "saved", "withdrawn"]


# --- SyncService quota handling ---

def _run_sync_with(repo: Repository, fetch_result):
    """Run the pipeline with the Gmail and ArbeitNow stages stubbed out."""
    from unittest.mock import patch

    from jobpilot.services.sync_service import SyncService

    with patch.object(SyncService, "_fetch_emails", return_value=fetch_result), \
         patch.object(SyncService, "_fetch_arbeitnow", return_value=0):
        return SyncService(repo).run()


def test_sync_run_records_last_sync_on_truncated_fetch(repo: Repository) -> None:
    """A quota-truncated fetch still completes the pipeline and records the sync time."""
    from jobpilot.gmail.fetcher import FetchResult

    result = _run_sync_with(
        repo, FetchResult(new_emails=3, truncated=True, processed=3, total=10),
    )

    assert result.fetch_truncated is True
    assert (result.new_emails, result.fetch_processed, result.fetch_total) == (3, 3, 10)
    assert repo.get_setting("last_sync_time") is not None


def test_truncated_sync_is_partial_not_done(repo: Repository) -> None:
    """`done` must mean every message was handled; a truncated run reports `partial`."""
    from jobpilot.gmail.fetcher import FetchResult
    from jobpilot.services.sync_state import STEP_DONE, STEP_PARTIAL, SyncState

    truncated = _run_sync_with(
        repo, FetchResult(new_emails=3, truncated=True, processed=3, total=10),
    )
    state = SyncState()
    state.start()
    state.finish(
        new_emails=truncated.new_emails, truncated=truncated.fetch_truncated,
        processed=truncated.fetch_processed, fetch_total=truncated.fetch_total,
    )
    partial = state.to_dict()
    assert partial["step"] == STEP_PARTIAL
    assert (partial["processed"], partial["fetch_total"]) == (3, 10)

    complete = _run_sync_with(
        repo, FetchResult(new_emails=10, truncated=False, processed=10, total=10),
    )
    state.start()
    state.finish(new_emails=complete.new_emails, truncated=complete.fetch_truncated,
                 processed=complete.fetch_processed, fetch_total=complete.fetch_total)
    assert state.to_dict()["step"] == STEP_DONE


# --- Scoring criteria reset ---

def _insert_labeled_job(
    db_conn: sqlite3.Connection, slug: str, label: str, labeled_at: str,
) -> None:
    """Insert a scraped job already carrying a user label at an explicit time."""
    title = "Senior iOS Engineer Remote" if label == "worth_checking" else "Sales Manager"
    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, company, location, description,"
        " url, user_label, labeled_at) VALUES (?,?,?,?,?,?,?,?)",
        ("linkedin", f"{title} {slug}", "Acme",
         "Remote" if label == "worth_checking" else "Lisbon",
         "swift ios mobile developer" if label == "worth_checking"
         else "cold calling quota crm",
         f"https://linkedin.com/jobs/view/{slug}", label, labeled_at),
    )
    db_conn.commit()


def _insert_not_a_job_feedback(db_conn: sqlite3.Connection, slug: str) -> None:
    """Insert an email plus a 'not_a_job' feedback row (a noise-model negative)."""
    db_conn.execute(
        "INSERT INTO emails (id, thread_id, sender, sender_domain, subject,"
        " body_text, received_at) VALUES (?,?,?,?,?,?,?)",
        (slug, f"thread_{slug}", "news@example.com", "example.com",
         "Newsletter", "weekly digest", "2026-01-01 00:00:00"),
    )
    db_conn.execute(
        "INSERT INTO user_feedback (email_id, label, feedback_at) VALUES (?,?,?)",
        (slug, "not_a_job", "2026-01-01 00:00:00"),
    )
    db_conn.commit()


def test_reset_makes_scoring_dormant_and_leaves_noise_alone(
    repo: Repository, db_conn,
) -> None:
    """After a reset the scoring model stops retraining while noise is unaffected."""
    from jobpilot.classifier.ml_trainer import MLTrainer

    for i in range(32):
        _insert_labeled_job(
            db_conn, f"old{i}", "worth_checking" if i % 2 else "skip",
            "2026-01-01T00:00:00.000000",
        )
    for i in range(6):
        _insert_not_a_job_feedback(db_conn, f"msg_noise_{i}")
    trainer = MLTrainer(repo)
    assert trainer.should_retrain("scoring") is True
    assert trainer.should_retrain("noise") is True

    repo.reset_scoring_criteria()

    assert trainer.should_retrain("scoring") is False
    assert trainer.train_all("scoring") == []
    assert trainer.should_retrain("noise") is True


def test_scoring_model_wakes_up_after_enough_post_reset_labels(
    repo: Repository, db_conn,
) -> None:
    """Thirty labels under the new criteria train and activate a scoring model again."""
    from jobpilot.classifier.ml_trainer import MLTrainer

    repo.reset_scoring_criteria()
    for i in range(30):
        _insert_labeled_job(
            db_conn, f"new{i}", "worth_checking" if i % 2 else "skip",
            "2026-12-01T00:00:00.000000",
        )

    model_ids = MLTrainer(repo).train_all("scoring")

    assert len(model_ids) == 4
    assert repo.get_active_model("scoring") is not None


def test_scoring_model_state_reports_dormancy_progress(
    repo: Repository, db_conn,
) -> None:
    """The settings context reports post-cutoff label progress toward the next model."""
    from jobpilot.config import settings

    _insert_labeled_job(db_conn, "old1", "skip", "2026-01-01T00:00:00.000000")
    repo.reset_scoring_criteria()
    _insert_labeled_job(db_conn, "new1", "worth_checking", "2026-12-01T00:00:00.000000")

    state = SettingsService(repo).scoring_model_state()

    assert state["labels"] == 1
    assert state["required"] == settings.min_training_samples
    assert state["dormant"] is True
    assert state["reset_at"] is not None


# --- Preference-aware scoring features ---

def _remote_only_prefs(repo: Repository) -> None:
    """Replace the seeded NL/SE/NO defaults with a remote-only location policy."""
    for category in ("location_primary", "location_secondary"):
        for pref in repo.get_preferences(category):
            repo.delete_preference(category, pref.value)
    repo.insert_preference("location_primary", "remote")


def test_scoring_features_follow_location_preferences(repo: Repository) -> None:
    """A remote job outranks an Amsterdam one once features read the preferences."""
    from jobpilot.classifier.ml_trainer import MLTrainer
    from jobpilot.classifier.rules import FEATURE_NAMES, compute_features

    _remote_only_prefs(repo)
    config = MLTrainer(repo).signal_config
    idx = FEATURE_NAMES.index("location_match")

    remote = compute_features("Flutter Engineer", "Location: Remote", config)
    onsite = compute_features("Flutter Engineer", "Location: Amsterdam", config)

    assert remote[idx] == 1.0
    assert onsite[idx] == 0.0


def test_hardcoded_basis_still_ranks_amsterdam_above_remote(repo: Repository) -> None:
    """Guards the regression: without a config, the old policy is still encoded."""
    from jobpilot.classifier.rules import FEATURE_NAMES, compute_features

    idx = FEATURE_NAMES.index("location_match")

    assert compute_features("Flutter Engineer", "Location: Remote")[idx] == 0.9
    assert compute_features("Flutter Engineer", "Location: Netherlands")[idx] == 1.0


def test_signal_config_is_cached_per_trainer_instance(repo: Repository) -> None:
    """One run scores every row against the same preferences; a new run sees edits."""
    from jobpilot.classifier.ml_trainer import MLTrainer

    _remote_only_prefs(repo)
    trainer = MLTrainer(repo)
    first = trainer.signal_config
    assert trainer.signal_config is first

    repo.insert_preference("location_primary", "berlin")

    assert "berlin" not in trainer.signal_config.locations
    assert "berlin" in MLTrainer(repo).signal_config.locations


def test_noise_features_ignore_preferences(repo: Repository) -> None:
    """Job-vs-not-a-job detection stays on the hardcoded signals."""
    from jobpilot.classifier.ml_trainer import MLTrainer
    from jobpilot.classifier.rules import compute_features

    before = MLTrainer(repo)._compute_noise_features("Flutter Engineer", "Remote", [])
    _remote_only_prefs(repo)
    after = MLTrainer(repo)._compute_noise_features("Flutter Engineer", "Remote", [])

    assert before == after == compute_features("Flutter Engineer", "Remote")


def _unprocessed(repo: Repository, email_id: str, sender: str, subject: str, platform: str | None):
    """Store an email awaiting classification."""
    from datetime import datetime

    from jobpilot.storage.models import Email

    repo.insert_email(Email(
        id=email_id, thread_id=f"t-{email_id}", sender=sender,
        sender_domain=sender.split("@")[-1], subject=subject,
        received_at=datetime(2026, 3, 1, 9, 0), platform=platform, processed=False,
    ))


class TestClassifyUnprocessedRejection:
    """Rejection is the detector's call, and it is not LinkedIn-specific."""

    def test_rejects_linkedin_social_noise(self, repo: Repository) -> None:
        _unprocessed(repo, "a", "notifications-noreply@linkedin.com",
                     "35 people viewed your profile", "linkedin")
        ClassificationService(repo).classify_unprocessed()
        email = repo.get_email("a")
        assert email.is_job_related is False
        assert email.non_job_rule == "linkedin_social"
        assert email.processed is True

    def test_rejects_a_non_linkedin_sender(self, repo: Repository) -> None:
        _unprocessed(repo, "b", "hi@turing.com",
                     "Upload your resume to be eligible for Turing roles", "turing")
        ClassificationService(repo).classify_unprocessed()
        email = repo.get_email("b")
        assert email.is_job_related is False
        assert email.non_job_rule == "platform_onboarding"

    def test_scores_genuine_job_mail_instead(self, repo: Repository) -> None:
        _unprocessed(repo, "c", "jobs-noreply@linkedin.com",
                     "Senior Flutter Developer at Proxify", "linkedin")
        ClassificationService(repo).classify_unprocessed()
        email = repo.get_email("c")
        assert email.is_job_related is True
        assert email.non_job_rule is None
        assert email.final_classification is not None
