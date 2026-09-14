"""Tests for assistant-assisted bulk labeling: provenance, gate, and audit trail."""

import json
import sqlite3
from pathlib import Path

import pytest
from jobpilot.services.label_service import (
    REASON_BELOW_THRESHOLD,
    REASON_MALFORMED,
    LabelBatchService,
)
from jobpilot.storage.label_repo import (
    ASSISTANT_SOURCE,
    REASON_ALREADY_LABELED,
    REASON_INVALID_LABEL,
    REASON_UNKNOWN_JOB,
    USER_SOURCE,
    LabelEntry,
)
from jobpilot.storage.migrations import _add_label_source
from jobpilot.storage.ml_repo import TRAINING_INCLUDES_ASSISTANT_KEY
from jobpilot.storage.models import ScrapedJob
from jobpilot.storage.repository import Repository

DEFAULT_MIN_CONFIDENCE = 0.95


def _make_job(repo: Repository, n: int) -> int:
    """Insert a scraped job and return its id."""
    repo.insert_scraped_job(ScrapedJob(
        id=None, source="linkedin", title=f"Flutter Engineer {n}",
        url=f"https://example.com/job/{n}", company="Acme", location="Remote",
    ))
    return repo.conn.execute(
        "SELECT id FROM scraped_jobs WHERE url = ?", (f"https://example.com/job/{n}",)
    ).fetchone()["id"]


def _label_row(repo: Repository, job_id: int) -> sqlite3.Row:
    """Return the label columns of one job."""
    return repo.conn.execute(
        "SELECT user_label, labeled_at, label_source FROM scraped_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()


def _write_jsonl(path: Path, entries: list[dict]) -> Path:
    """Write entries as JSONL and return the path."""
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def service(repo: Repository, tmp_path: Path) -> LabelBatchService:
    """Batch service writing its audit logs into the test's tmp dir."""
    return LabelBatchService(repo, tmp_path / "logs")


def _run(service, repo, tmp_path, entries, **kwargs):
    """Write a JSONL file of entries and run a batch over it."""
    path = _write_jsonl(tmp_path / "labels.jsonl", entries)
    return service.run_batch(
        path, kwargs.pop("min_confidence", DEFAULT_MIN_CONFIDENCE), **kwargs
    )


# --- Migration ---


def test_migration_backfills_user_source_only_for_labeled_rows(repo: Repository):
    """Labeled rows become 'user'; unlabeled rows keep a NULL source."""
    labeled, unlabeled = _make_job(repo, 1), _make_job(repo, 2)
    repo.update_scraped_job_label(labeled, "skip")
    # Rewind to a genuinely pre-migration schema so the migration does the work.
    repo.conn.execute("ALTER TABLE scraped_jobs DROP COLUMN label_source")
    repo.conn.commit()

    _add_label_source(repo.conn)

    assert _label_row(repo, labeled)["label_source"] == USER_SOURCE
    assert _label_row(repo, unlabeled)["label_source"] is None


def test_migration_is_idempotent(repo: Repository):
    """A second run neither errors nor re-attributes an assistant label."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "skip", ASSISTANT_SOURCE)

    _add_label_source(repo.conn)
    _add_label_source(repo.conn)

    assert _label_row(repo, job_id)["label_source"] == ASSISTANT_SOURCE


def test_schema_carries_label_source_on_a_fresh_database(repo: Repository):
    """A database built from SCHEMA_SQL has the column without any migration."""
    cols = {r[1] for r in repo.conn.execute("PRAGMA table_info(scraped_jobs)").fetchall()}
    assert "label_source" in cols


# --- Applying ---


def test_valid_entry_is_written_with_assistant_source(service, repo, tmp_path):
    """A confident entry lands with an assistant source and a UTC stamp."""
    job_id = _make_job(repo, 1)

    run = _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.97, "reason": "Hybrid"},
    ])

    row = _label_row(repo, job_id)
    assert (run.applied, run.rejected) == (1, 0)
    assert row["user_label"] == "skip"
    assert row["label_source"] == ASSISTANT_SOURCE
    now = repo.conn.execute("SELECT datetime('now') AS n").fetchone()["n"]
    assert row["labeled_at"][:10] == now[:10]
    assert "T" not in row["labeled_at"]


def test_below_threshold_entry_is_rejected_and_nothing_written(service, repo, tmp_path):
    """A 0.80 judgment under the 0.95 floor leaves the job in the queue."""
    job_id = _make_job(repo, 1)

    run = _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.80},
    ])

    assert (run.applied, run.rejected, run.below_threshold) == (0, 1, 1)
    assert _label_row(repo, job_id)["user_label"] is None
    assert _log_reasons(run)[0] == REASON_BELOW_THRESHOLD


def test_missing_confidence_falls_below_every_floor(service, repo, tmp_path):
    """An unstated confidence is not a high one."""
    job_id = _make_job(repo, 1)

    run = _run(service, repo, tmp_path, [{"id": job_id, "label": "skip"}])

    assert run.below_threshold == 1
    assert _label_row(repo, job_id)["user_label"] is None


def test_label_outside_the_vocabulary_is_rejected(service, repo, tmp_path):
    """'maybe' is not a label; nothing is written."""
    job_id = _make_job(repo, 1)

    run = _run(service, repo, tmp_path, [
        {"id": job_id, "label": "maybe", "confidence": 0.99},
    ])

    assert (run.applied, run.rejected) == (0, 1)
    assert _log_reasons(run)[0] == REASON_INVALID_LABEL
    assert _label_row(repo, job_id)["user_label"] is None


def test_already_labeled_job_is_left_alone(service, repo, tmp_path):
    """A hand-clicked label and its 'user' source survive a bulk run."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "worth_checking")

    run = _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.99},
    ])

    row = _label_row(repo, job_id)
    assert (run.applied, run.rejected) == (0, 1)
    assert _log_reasons(run)[0] == REASON_ALREADY_LABELED
    assert (row["user_label"], row["label_source"]) == ("worth_checking", USER_SOURCE)


def test_force_overwrites_an_existing_label(service, repo, tmp_path):
    """--force flips both the label and its source."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "worth_checking")

    run = _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.99},
    ], force=True)

    row = _label_row(repo, job_id)
    assert run.applied == 1
    assert (row["user_label"], row["label_source"]) == ("skip", ASSISTANT_SOURCE)


def test_unknown_id_is_rejected_without_aborting_the_run(service, repo, tmp_path):
    """A bad id costs its own entry, not the file."""
    job_id = _make_job(repo, 1)

    run = _run(service, repo, tmp_path, [
        {"id": 999999, "label": "skip", "confidence": 0.99},
        {"id": job_id, "label": "skip", "confidence": 0.99},
    ])

    assert (run.applied, run.rejected) == (1, 1)
    assert _log_reasons(run)[0] == REASON_UNKNOWN_JOB
    assert _label_row(repo, job_id)["user_label"] == "skip"


def test_one_malformed_line_does_not_abort_the_run(service, repo, tmp_path):
    """Nine valid entries apply around a tenth that will not parse."""
    ids = [_make_job(repo, n) for n in range(9)]
    path = tmp_path / "labels.jsonl"
    lines = [json.dumps({"id": i, "label": "skip", "confidence": 0.99}) for i in ids]
    lines.insert(4, "{not json at all")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    run = service.run_batch(path, DEFAULT_MIN_CONFIDENCE)

    assert (run.applied, run.rejected) == (9, 1)
    assert REASON_MALFORMED in _log_reasons(run)
    assert _assistant_count(repo) == 9


def test_dry_run_reports_counts_and_writes_nothing(service, repo, tmp_path):
    """Ten valid entries report as applied while the table stays untouched."""
    ids = [_make_job(repo, n) for n in range(10)]

    run = _run(service, repo, tmp_path, [
        {"id": i, "label": "skip", "confidence": 0.99} for i in ids
    ], dry_run=True)

    assert run.applied == 10
    assert run.dry_run is True
    assert _assistant_count(repo) == 0


# --- Reverting ---


def test_revert_clears_only_assistant_labels(service, repo, tmp_path):
    """Bulk labels go back to unlabeled; hand-clicked ones are untouched."""
    bulk_ids = [_make_job(repo, n) for n in range(5)]
    hand_id = _make_job(repo, 99)
    repo.update_scraped_job_label(hand_id, "worth_checking")
    _run(service, repo, tmp_path, [
        {"id": i, "label": "skip", "confidence": 0.99} for i in bulk_ids
    ])

    run = service.revert(ASSISTANT_SOURCE)

    assert run.applied == 5
    for job_id in bulk_ids:
        row = _label_row(repo, job_id)
        assert (row["user_label"], row["labeled_at"], row["label_source"]) == (None,) * 3
    hand = _label_row(repo, hand_id)
    assert (hand["user_label"], hand["label_source"]) == ("worth_checking", USER_SOURCE)


# --- Audit log ---


def test_audit_log_has_one_line_per_input_entry(service, repo, tmp_path):
    """A mixed run logs every entry with its outcome and rejection reason."""
    good, already = _make_job(repo, 1), _make_job(repo, 2)
    repo.update_scraped_job_label(already, "skip")

    run = _run(service, repo, tmp_path, [
        {"id": good, "label": "skip", "confidence": 0.99},
        {"id": already, "label": "skip", "confidence": 0.99},
        {"id": good, "label": "skip", "confidence": 0.10},
    ])

    lines = [json.loads(ln) for ln in run.log_path.read_text().splitlines()]
    assert len(lines) == 3
    assert lines[0]["outcome"] == "applied" and lines[0]["reason"] is None
    assert lines[1]["reason"] == REASON_ALREADY_LABELED
    assert lines[2]["reason"] == REASON_BELOW_THRESHOLD


def test_dry_run_writes_an_inspectable_log(service, repo, tmp_path):
    """A preview is auditable before committing to it."""
    job_id = _make_job(repo, 1)

    run = _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.99},
    ], dry_run=True)

    logged = json.loads(run.log_path.read_text().splitlines()[0])
    assert logged["dry_run"] is True
    assert logged["outcome"] == "applied"


def test_each_run_gets_its_own_log(service, repo, tmp_path):
    """A preview and the apply that follows it must not share one log file."""
    job_id = _make_job(repo, 1)
    entries = [{"id": job_id, "label": "skip", "confidence": 0.99}]

    preview = _run(service, repo, tmp_path, entries, dry_run=True)
    applied = _run(service, repo, tmp_path, entries)

    assert preview.log_path != applied.log_path
    assert len(preview.log_path.read_text().splitlines()) == 1
    assert len(applied.log_path.read_text().splitlines()) == 1


# --- Training gate ---


def test_assistant_labels_are_held_out_of_training_by_default(service, repo, tmp_path):
    """The default keeps the training count honest about what it learns from."""
    hand_id = _make_job(repo, 99)
    repo.update_scraped_job_label(hand_id, "worth_checking")
    bulk_ids = [_make_job(repo, n) for n in range(5)]
    _run(service, repo, tmp_path, [
        {"id": i, "label": "skip", "confidence": 0.99} for i in bulk_ids
    ])

    assert _assistant_count(repo) == 5
    assert len(repo.get_scoring_training_data()) == 1


def test_opting_in_admits_assistant_labels_without_relabeling(service, repo, tmp_path):
    """Flipping the setting alone raises the count by the held-out labels."""
    hand_id = _make_job(repo, 99)
    repo.update_scraped_job_label(hand_id, "worth_checking")
    bulk_ids = [_make_job(repo, n) for n in range(5)]
    _run(service, repo, tmp_path, [
        {"id": i, "label": "skip", "confidence": 0.99} for i in bulk_ids
    ])

    repo.set_setting(TRAINING_INCLUDES_ASSISTANT_KEY, "true")

    assert len(repo.get_scoring_training_data()) == 6


def test_rows_predating_the_column_still_train(repo: Repository):
    """A NULL source is not an assistant source — historical labels still count."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "worth_checking")
    repo.conn.execute("UPDATE scraped_jobs SET label_source = NULL WHERE id = ?", (job_id,))
    repo.conn.commit()

    assert len(repo.get_scoring_training_data()) == 1


# --- Provenance surfaced to the UI ---


def test_recent_labels_carry_the_authoring_source(service, repo, tmp_path):
    """Bulk-labeled jobs read 'assistant'; email feedback always reads 'user'."""
    job_id = _make_job(repo, 1)
    _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.99},
    ])
    _insert_email_feedback(repo, "abc123def456", "worth_checking")

    by_type = {
        item["item_type"]: item["label_source"]
        for item in repo.get_recent_predictions_comparison()
    }
    assert by_type["scraped_job"] == ASSISTANT_SOURCE
    assert by_type["email"] == USER_SOURCE


def test_stats_recent_labels_carry_the_authoring_source(service, repo, tmp_path):
    """The list the stats page actually renders carries the source too."""
    from jobpilot.storage.predictions_repo import PredictionsRepository

    job_id = _make_job(repo, 1)
    _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.99},
    ])
    _insert_email_feedback(repo, "abc123def456", "skip")

    by_type = {
        item["item_type"]: item["label_source"]
        for item in PredictionsRepository(repo.conn).recent_scoring()
    }
    assert by_type["scraped_job"] == ASSISTANT_SOURCE
    assert by_type["email"] == USER_SOURCE


def test_ui_label_defaults_to_the_user_source(repo: Repository):
    """A click in the UI is attributed to the user without the caller saying so."""
    job_id = _make_job(repo, 1)

    repo.update_scraped_job_label(job_id, "worth_checking")

    assert _label_row(repo, job_id)["label_source"] == USER_SOURCE


def test_undoing_a_label_clears_its_source(repo: Repository):
    """The existing undo button leaves no orphaned provenance behind."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "skip", ASSISTANT_SOURCE)

    repo.update_scraped_job_label(job_id, None)

    row = _label_row(repo, job_id)
    assert (row["user_label"], row["labeled_at"], row["label_source"]) == (None,) * 3


def test_review_queue_count_drops_by_exactly_the_number_applied(service, repo, tmp_path):
    """Labeling removes jobs from the queue one for one."""
    ids = [_make_job(repo, n) for n in range(6)]
    before = repo.count_scraped_jobs_for_review()

    run = _run(service, repo, tmp_path, [
        {"id": i, "label": "skip", "confidence": 0.99} for i in ids[:4]
    ])

    assert run.applied == 4
    assert repo.count_scraped_jobs_for_review() == before - 4


# --- Repository-level edges ---


def test_duplicate_ids_in_one_file_settle_on_the_last_entry(repo: Repository):
    """executemany applies both writes in order; the file's last word wins."""
    job_id = _make_job(repo, 1)

    repo.labels.apply_labels([
        LabelEntry(job_id, "skip", 0.99),
        LabelEntry(job_id, "worth_checking", 0.99),
    ])

    assert _label_row(repo, job_id)["user_label"] == "worth_checking"


def test_empty_entry_list_is_a_no_op(repo: Repository):
    """An empty file writes nothing and rejects nothing."""
    result = repo.labels.apply_labels([])

    assert (result.applied, result.rejected) == ([], [])


def _assistant_count(repo: Repository) -> int:
    """Count rows currently carrying an assistant label."""
    return repo.labels.count_by_source(ASSISTANT_SOURCE)


def _log_reasons(run) -> list[str | None]:
    """Return the rejection reason of each audit-log line, in input order."""
    return [
        json.loads(line)["reason"] for line in run.log_path.read_text().splitlines()
    ]


def _insert_email_feedback(repo: Repository, email_id: str, label: str) -> None:
    """Insert an email plus a hand-authored feedback label on it."""
    from datetime import datetime

    from jobpilot.storage.models import Email, UserFeedback

    repo.insert_email(Email(
        id=email_id, thread_id="t1", sender="jobs@linkedin.com",
        sender_domain="linkedin.com", subject="A role", received_at=datetime.now(),
    ))
    repo.insert_feedback(UserFeedback(id=None, email_id=email_id, label=label))


def test_reason_is_stored_on_the_row(service, repo, tmp_path):
    """The stated rationale reaches the database, not just the audit log."""
    job_id = _make_job(repo, 1)

    _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.99,
         "reason": "Hybrid: 3 days in office"},
    ])

    row = repo.conn.execute(
        "SELECT label_reason FROM scraped_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    assert row["label_reason"] == "Hybrid: 3 days in office"
    assert repo.get_scraped_job(job_id).label_reason == "Hybrid: 3 days in office"


def test_reason_reaches_the_stats_list(service, repo, tmp_path):
    """The recent-labels row carries the rationale the page renders."""
    from jobpilot.storage.predictions_repo import PredictionsRepository

    job_id = _make_job(repo, 1)
    _run(service, repo, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.99, "reason": "Onsite in Stockholm"},
    ])

    item = next(
        i for i in PredictionsRepository(repo.conn).recent_scoring()
        if i["item_type"] == "scraped_job"
    )
    assert item["label_reason"] == "Onsite in Stockholm"


def test_an_entry_without_a_reason_stores_null(service, repo, tmp_path):
    """A reason is optional; its absence is recorded as absence."""
    job_id = _make_job(repo, 1)

    _run(service, repo, tmp_path, [{"id": job_id, "label": "skip", "confidence": 0.99}])

    assert repo.get_scraped_job(job_id).label_reason is None


def test_a_hand_click_clears_any_previous_reason(repo: Repository):
    """Relabeling by hand must not leave a bulk run's rationale attached."""
    job_id = _make_job(repo, 1)
    repo.labels.apply_labels([LabelEntry(job_id, "skip", 0.99, "Hybrid")])

    repo.update_scraped_job_label(job_id, "worth_checking")

    job = repo.get_scraped_job(job_id)
    assert (job.user_label, job.label_source, job.label_reason) == (
        "worth_checking", USER_SOURCE, None,
    )


def test_revert_clears_the_reason_too(repo: Repository):
    """Reverting leaves no orphaned rationale behind."""
    job_id = _make_job(repo, 1)
    repo.labels.apply_labels([LabelEntry(job_id, "skip", 0.99, "Hybrid")])

    repo.labels.clear_labels_by_source(ASSISTANT_SOURCE)

    assert repo.get_scraped_job(job_id).label_reason is None


def _report(repo: Repository, tmp_path: Path) -> str:
    """Render the review document to a temp file and return its text."""
    from jobpilot.services.label_report import write_label_report

    return write_label_report(repo, tmp_path / "out" / "result.md").read_text()


def test_report_groups_rows_sharing_a_reason(service, repo, tmp_path):
    """A reason used many times becomes one auditable section, not many rows."""
    ids = [_make_job(repo, n) for n in range(4)]
    _run(service, repo, tmp_path, [
        {"id": i, "label": "skip", "confidence": 0.99, "reason": "No mobile component"}
        for i in ids[:3]
    ] + [{"id": ids[3], "label": "skip", "confidence": 0.99, "reason": "Onsite in Oslo"}])

    text = _report(repo, tmp_path)
    assert "### No mobile component (3)" in text
    assert "### Individually judged (1)" in text
    assert "Onsite in Oslo" in text


def test_report_leads_with_what_to_act_on(service, repo, tmp_path):
    """worth_checking must come before skip — it is the section with work in it."""
    keep, drop = _make_job(repo, 1), _make_job(repo, 2)
    _run(service, repo, tmp_path, [
        {"id": drop, "label": "skip", "confidence": 0.99, "reason": "Onsite"},
        {"id": keep, "label": "worth_checking", "confidence": 0.99, "reason": "Fully remote"},
    ])

    text = _report(repo, tmp_path)
    assert text.index("## Worth checking") < text.index("## Skip")


def test_report_links_only_safe_urls(repo: Repository, tmp_path: Path):
    """A javascript: url must never become a Markdown link."""
    repo.insert_scraped_job(ScrapedJob(
        id=None, source="linkedin", title="Evil", url="javascript:alert(1)",
    ))
    job_id = repo.conn.execute(
        "SELECT id FROM scraped_jobs WHERE url = 'javascript:alert(1)'"
    ).fetchone()["id"]
    repo.labels.apply_labels([LabelEntry(job_id, "skip", 0.99, "Not a job")])

    text = _report(repo, tmp_path)
    assert "javascript:" not in text
    assert "Evil" in text


def test_report_states_the_unlabeled_remainder(service, repo, tmp_path):
    """The queue left behind is explained, so its size is not read as failure."""
    labeled = _make_job(repo, 1)
    _make_job(repo, 2)
    _run(service, repo, tmp_path, [
        {"id": labeled, "label": "skip", "confidence": 0.99, "reason": "Onsite"},
    ])

    assert "## Left unlabeled (1)" in _report(repo, tmp_path)


def test_report_handles_having_nothing_to_report(repo: Repository, tmp_path: Path):
    """With no bulk labels the document says so rather than rendering empty headings."""
    text = _report(repo, tmp_path)

    assert "No labels are currently authored by a bulk run." in text
    assert "## Skip" not in text


def test_report_neutralises_markdown_in_a_scraped_title(repo: Repository, tmp_path: Path):
    """A title that closes the link and opens its own must not become a link.

    Checking the url scheme alone is not enough — every scraped field is untrusted.
    """
    repo.insert_scraped_job(ScrapedJob(
        id=None, source="linkedin", title="Nice role](javascript:alert(1))",
        url="https://example.com/ok", company="A[b](c)", location="X)(Y",
    ))
    job_id = repo.conn.execute(
        "SELECT id FROM scraped_jobs WHERE url = 'https://example.com/ok'"
    ).fetchone()["id"]
    repo.labels.apply_labels([LabelEntry(job_id, "skip", 0.99, "See [here](javascript:0)")])

    text = _report(repo, tmp_path)

    # The dangerous sequence is "](" followed by a scheme — that is what closes the
    # intended link and opens a new one. Escaped, it is inert text.
    assert "](javascript:" not in text
    assert "(1))" not in text                    # the title's own parens are escaped
    assert "https://example.com/ok" in text      # the one real link survives
    assert "Nice role" in text


def test_report_breaks_spelling_ties_deterministically(repo: Repository, tmp_path: Path):
    """Two equally common spellings must pick the same heading on every run."""
    ids = [_make_job(repo, n) for n in range(4)]
    repo.labels.apply_labels([
        LabelEntry(ids[0], "skip", 0.99, "Remote-first"),
        LabelEntry(ids[1], "skip", 0.99, "Remote-first"),
        LabelEntry(ids[2], "skip", 0.99, "remote-first"),
        LabelEntry(ids[3], "skip", 0.99, "remote-first"),
    ])

    headings = {
        line for line in _report(repo, tmp_path).splitlines() if line.startswith("### ")
    }
    assert headings == {"### Remote-first (4)"}
