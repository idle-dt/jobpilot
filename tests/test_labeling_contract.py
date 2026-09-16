"""Tests for the labeling contract: hand-backs, the rejection guard, coverage, tracking.

Two lines these defend. A hand-back is not a label and never becomes one. And a label the
user cancelled can never be re-applied by a run — enforced in the repository, so an agent
that ignores its instructions is still stopped.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from jobpilot.services.label_service import (
    OUTCOME_PASSED,
    LabelBatchService,
)
from jobpilot.storage.label_repo import (
    ASSISTANT_SOURCE,
    LABEL_VOCABULARY,
    PASSED,
    REASON_ALREADY_LABELED,
    REASON_ALREADY_PASSED,
    REASON_MISSING_REASON,
    REASON_PREVIOUSLY_REJECTED,
    REASON_UNKNOWN_JOB,
    USER_SOURCE,
    LabelEntry,
)
from jobpilot.storage.models import ScrapedJob
from jobpilot.storage.repository import Repository

DEFAULT_MIN_CONFIDENCE = 0.95
WORTH_CHECKING = "worth_checking"


def _make_job(repo: Repository, n: int, classification: str = WORTH_CHECKING) -> int:
    """Insert a scraped job and return its id.

    ``insert_scraped_job`` does not carry classification, so it is set directly — the
    review queue is defined by it, and these tests turn on queue membership.
    """
    repo.insert_scraped_job(ScrapedJob(
        id=None, source="linkedin", title=f"Senior Android Engineer {n}",
        url=f"https://example.com/job/{n}", company="Acme", location="Stockholm",
    ))
    job_id = repo.conn.execute(
        "SELECT id FROM scraped_jobs WHERE url = ?", (f"https://example.com/job/{n}",)
    ).fetchone()["id"]
    repo.conn.execute(
        "UPDATE scraped_jobs SET classification = ? WHERE id = ?", (classification, job_id)
    )
    repo.conn.commit()
    return job_id


def _row(repo: Repository, job_id: int) -> sqlite3.Row:
    """Return the verdict columns of one job."""
    return repo.conn.execute(
        "SELECT user_label, label_source, ai_passed_at, ai_passed_reason"
        " FROM scraped_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()


def _pass(job_id: int, reason: str | None = "under the confidence floor") -> LabelEntry:
    """Build a hand-back entry for one job."""
    return LabelEntry(job_id=job_id, label=PASSED, confidence=0.4, reason=reason)


def _label(job_id: int, label: str = WORTH_CHECKING) -> LabelEntry:
    """Build a confident label entry for one job."""
    return LabelEntry(job_id=job_id, label=label, confidence=0.99, reason="mobile is the role")


@pytest.fixture
def service(repo: Repository, tmp_path: Path) -> LabelBatchService:
    """Batch service writing its audit logs into the test's tmp dir."""
    return LabelBatchService(repo, tmp_path / "logs")


def _run(service, tmp_path, entries, **kwargs):
    """Write a JSONL file of entries and run a batch over it."""
    path = tmp_path / "labels.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return service.run_batch(
        path, kwargs.pop("min_confidence", DEFAULT_MIN_CONFIDENCE), **kwargs
    )


# --- The vocabulary boundary ---


def test_passed_is_not_a_label():
    """A hand-back must never be writable as a label."""
    assert PASSED not in LABEL_VOCABULARY


# --- Hand-backs ---


def test_pass_leaves_the_job_in_the_inbox(repo: Repository):
    """A handed-back job stays in the review queue: it is the user's to label."""
    job_id = _make_job(repo, 1)

    repo.labels.mark_passed([_pass(job_id)])

    assert job_id in {j.id for j in repo.get_scraped_jobs_for_review()}
    assert repo.count_scraped_jobs_for_review() == 1
    row = _row(repo, job_id)
    assert row["user_label"] is None
    assert row["ai_passed_reason"] == "under the confidence floor"


def test_a_passed_job_is_not_exported_again(repo: Repository):
    """The point of the flag: the next run never re-reads it."""
    kept, handed_back = _make_job(repo, 1), _make_job(repo, 2)

    repo.labels.mark_passed([_pass(handed_back)])

    assert [r["id"] for r in repo.export_rows()] == [kept]
    assert repo.review_queue_ids() == [kept]


def test_passed_reset_returns_the_job_to_the_export(repo: Repository, service):
    """New criteria deserve a fresh look at what the old ones passed over."""
    job_id = _make_job(repo, 1)
    repo.labels.mark_passed([_pass(job_id)])

    service.reset_passed()

    assert [r["id"] for r in repo.export_rows()] == [job_id]
    assert _row(repo, job_id)["ai_passed_at"] is None


def test_pass_without_a_reason_is_refused(repo: Repository):
    """A reasonless hand-back is an omission with extra steps."""
    job_id = _make_job(repo, 1)

    result = repo.labels.mark_passed([_pass(job_id, reason=None)])

    assert [r.reason for r in result.rejected] == [REASON_MISSING_REASON]
    assert _row(repo, job_id)["ai_passed_at"] is None


def test_pass_with_a_blank_reason_is_refused(repo: Repository):
    """Whitespace is not a stated reason."""
    job_id = _make_job(repo, 1)

    result = repo.labels.mark_passed([_pass(job_id, reason="   ")])

    assert [r.reason for r in result.rejected] == [REASON_MISSING_REASON]


def test_pass_never_overrides_a_label(repo: Repository):
    """A job the user already judged is not handed back."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "skip")

    result = repo.labels.mark_passed([_pass(job_id)])

    assert [r.reason for r in result.rejected] == [REASON_ALREADY_LABELED]
    assert _row(repo, job_id)["user_label"] == "skip"


def test_passing_twice_is_refused(repo: Repository):
    """The second hand-back is refused, not silently reapplied."""
    job_id = _make_job(repo, 1)
    repo.labels.mark_passed([_pass(job_id)])

    result = repo.labels.mark_passed([_pass(job_id, reason="different wording")])

    assert [r.reason for r in result.rejected] == [REASON_ALREADY_PASSED]


def test_passing_an_unknown_job_is_refused(repo: Repository):
    """An id with no row behind it writes nothing."""
    result = repo.labels.mark_passed([_pass(999_999)])

    assert [r.reason for r in result.rejected] == [REASON_UNKNOWN_JOB]


def test_pass_dry_run_writes_nothing(repo: Repository):
    """A preview reports its decisions and leaves every row untouched."""
    job_id = _make_job(repo, 1)

    result = repo.labels.mark_passed([_pass(job_id)], dry_run=True)

    assert len(result.applied) == 1
    assert _row(repo, job_id)["ai_passed_at"] is None


# --- The rejection guard ---


def test_a_run_cannot_re_apply_a_cancelled_label(repo: Repository):
    """The core guard: a cancelled verdict can never come back from a run."""
    job_id = _make_job(repo, 1)
    repo.labels.rejections.record(job_id, WORTH_CHECKING, ASSISTANT_SOURCE, "was wrong")

    result = repo.labels.apply_labels([_label(job_id, WORTH_CHECKING)])

    assert [r.reason for r in result.rejected] == [REASON_PREVIOUSLY_REJECTED]
    assert _row(repo, job_id)["user_label"] is None


def test_the_guard_is_per_label(repo: Repository):
    """Cancelling worth_checking must not block a later skip."""
    job_id = _make_job(repo, 1)
    repo.labels.rejections.record(job_id, WORTH_CHECKING, ASSISTANT_SOURCE, "was wrong")

    result = repo.labels.apply_labels([_label(job_id, "skip")])

    assert result.rejected == []
    assert _row(repo, job_id)["user_label"] == "skip"


def test_force_does_not_override_a_cancel(repo: Repository):
    """--force overrides a label, never the user's own cancel."""
    job_id = _make_job(repo, 1)
    repo.labels.rejections.record(job_id, WORTH_CHECKING, ASSISTANT_SOURCE, "was wrong")

    result = repo.labels.apply_labels([_label(job_id, WORTH_CHECKING)], force=True)

    assert [r.reason for r in result.rejected] == [REASON_PREVIOUSLY_REJECTED]


def test_a_user_click_is_never_blocked_and_clears_the_rejection(repo: Repository):
    """Changing your mind is always allowed, and un-blocks future runs."""
    job_id = _make_job(repo, 1)
    repo.labels.rejections.record(job_id, WORTH_CHECKING, ASSISTANT_SOURCE, "was wrong")

    repo.update_scraped_job_label(job_id, WORTH_CHECKING)

    row = _row(repo, job_id)
    assert row["user_label"] == WORTH_CHECKING
    assert row["label_source"] == USER_SOURCE
    assert repo.labels.rejections.labels_for(job_id) == set()


def test_rejections_survive_a_label_revert(repo: Repository, service):
    """They are the user's decisions, not the assistant's output."""
    job_id = _make_job(repo, 1)
    repo.labels.rejections.record(job_id, WORTH_CHECKING, ASSISTANT_SOURCE, "was wrong")
    other = _make_job(repo, 2)
    repo.labels.apply_labels([_label(other, "skip")])

    service.revert(ASSISTANT_SOURCE)

    assert repo.labels.rejections.labels_for(job_id) == {WORTH_CHECKING}
    assert _row(repo, other)["user_label"] is None


def test_a_conflict_does_not_abort_the_run(repo: Repository, service, tmp_path):
    """One refused entry must not cost the run its good work."""
    blocked, good = _make_job(repo, 1), _make_job(repo, 2)
    repo.labels.rejections.record(blocked, WORTH_CHECKING, ASSISTANT_SOURCE, "was wrong")

    run = _run(service, tmp_path, [
        {"id": blocked, "label": WORTH_CHECKING, "confidence": 0.99, "reason": "mobile"},
        {"id": good, "label": "skip", "confidence": 0.99, "reason": "iOS only"},
    ])

    assert (run.applied, run.rejected) == (1, 1)
    assert run.conflicts == [blocked]
    assert _row(repo, good)["user_label"] == "skip"


# --- The confidence floor ---


def test_the_floor_does_not_apply_to_hand_backs(repo: Repository, service, tmp_path):
    """A hand-back is the uncertainty being declared, so no floor gates it."""
    job_id = _make_job(repo, 1)

    run = _run(service, tmp_path, [
        {"id": job_id, "label": PASSED, "confidence": 0.4, "reason": "no work mode"},
    ])

    assert (run.passed, run.rejected) == (1, 0)
    assert _row(repo, job_id)["ai_passed_at"] is not None


def test_the_floor_still_applies_to_labels(repo: Repository, service, tmp_path):
    """Unchanged for labels — the exemption is asymmetric by design."""
    job_id = _make_job(repo, 1)

    run = _run(service, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.4, "reason": "iOS only"},
    ])

    assert (run.applied, run.rejected, run.below_threshold) == (0, 1, 1)
    assert _row(repo, job_id)["user_label"] is None


def test_a_hand_back_is_logged_with_its_own_outcome(repo: Repository, service, tmp_path):
    """The audit log distinguishes a hand-back from an applied label."""
    job_id = _make_job(repo, 1)

    run = _run(service, tmp_path, [
        {"id": job_id, "label": PASSED, "confidence": 0.4, "reason": "no work mode"},
    ])

    logged = [json.loads(line) for line in run.log_path.read_text().splitlines()]
    assert [e["outcome"] for e in logged] == [OUTCOME_PASSED]


# --- Coverage ---


def test_coverage_names_the_rows_the_run_never_mentioned(repo: Repository, service, tmp_path):
    """Silent omission becomes a listed set of ids."""
    ids = [_make_job(repo, n) for n in range(1, 6)]

    run = _run(service, tmp_path, [
        {"id": ids[0], "label": "skip", "confidence": 0.99, "reason": "iOS only"},
        {"id": ids[1], "label": PASSED, "confidence": 0.4, "reason": "no work mode"},
    ])

    assert run.queue_size == 5
    assert run.unaccounted == sorted(ids[2:])


def test_full_coverage_reports_nothing_unaccounted(repo: Repository, service, tmp_path):
    """A run accounting for every queue row leaves the list empty."""
    ids = [_make_job(repo, n) for n in (1, 2)]

    run = _run(service, tmp_path, [
        {"id": job_id, "label": PASSED, "confidence": 0.4, "reason": "no work mode"}
        for job_id in ids
    ])

    assert (run.queue_size, run.unaccounted) == (2, [])


def test_a_refused_entry_still_counts_as_accounted(repo: Repository, service, tmp_path):
    """Coverage asks what the run looked at, not what it managed to write."""
    job_id = _make_job(repo, 1)

    run = _run(service, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.1, "reason": "iOS only"},
    ])

    assert run.unaccounted == []


def test_auto_skipped_jobs_are_outside_coverage(repo: Repository, service, tmp_path):
    """The scorer's own 'skip' verdicts are not the run's to account for."""
    _make_job(repo, 1, classification="skip")
    queued = _make_job(repo, 2)

    run = _run(service, tmp_path, [])

    assert run.unaccounted == [queued]


# --- The Tracker hookup ---


def test_a_bulk_worth_checking_reaches_the_tracker(repo: Repository, service, tmp_path):
    """The gap this whole effort exists to close."""
    job_id = _make_job(repo, 1)

    run = _run(service, tmp_path, [
        {"id": job_id, "label": WORTH_CHECKING, "confidence": 0.99, "reason": "mobile"},
    ])

    app = repo.get_application_by_scraped_job_id(job_id)
    assert run.tracked == 1
    assert app is not None
    assert app.status == "saved"


def test_a_bulk_skip_does_not_reach_the_tracker(repo: Repository, service, tmp_path):
    """Only worth_checking is tracked, matching what a UI click does."""
    job_id = _make_job(repo, 1)

    run = _run(service, tmp_path, [
        {"id": job_id, "label": "skip", "confidence": 0.99, "reason": "iOS only"},
    ])

    assert run.tracked == 0
    assert repo.get_application_by_scraped_job_id(job_id) is None


def test_tracking_is_idempotent(repo: Repository, service, tmp_path):
    """A job already tracked gains no second application."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, WORTH_CHECKING)
    from jobpilot.services.tracker_service import TrackerService
    TrackerService(repo).auto_track_scraped_job(job_id)

    run = _run(service, tmp_path, [
        {"id": job_id, "label": WORTH_CHECKING, "confidence": 0.99, "reason": "mobile"},
    ], force=True)

    assert run.tracked == 0
    assert repo.conn.execute(
        "SELECT COUNT(*) c FROM applications WHERE scraped_job_id = ?", (job_id,)
    ).fetchone()["c"] == 1


def test_dry_run_tracks_nothing(repo: Repository, service, tmp_path):
    """A preview reports what it would track and writes no application."""
    job_id = _make_job(repo, 1)

    run = _run(service, tmp_path, [
        {"id": job_id, "label": WORTH_CHECKING, "confidence": 0.99, "reason": "mobile"},
    ], dry_run=True)

    assert run.tracked == 1
    assert repo.get_application_by_scraped_job_id(job_id) is None


# --- Hand-backs stay out of the model ---


def test_hand_backs_never_reach_training_data(repo: Repository):
    """A pass is a statement about the run's confidence, not about the job."""
    job_id = _make_job(repo, 1)
    before = repo.ml.get_scoring_training_data()
    labeled_before = repo.conn.execute(
        "SELECT COUNT(*) c FROM scraped_jobs WHERE user_label IS NOT NULL"
    ).fetchone()["c"]

    repo.labels.mark_passed([_pass(job_id)])

    assert repo.ml.get_scoring_training_data() == before
    assert repo.conn.execute(
        "SELECT COUNT(*) c FROM scraped_jobs WHERE user_label IS NOT NULL"
    ).fetchone()["c"] == labeled_before


# --- The export ---


def test_export_carries_the_cancelled_labels(repo: Repository):
    """An agent must be able to see what it is barred from concluding."""
    job_id = _make_job(repo, 1)
    repo.labels.rejections.record(job_id, WORTH_CHECKING, ASSISTANT_SOURCE, "was wrong")

    rows = repo.export_rows()

    assert [r["rejected_labels"] for r in rows] == [[WORTH_CHECKING]]
    assert json.loads(json.dumps(rows)) == rows


def test_export_excludes_labeled_and_auto_skipped(repo: Repository):
    """The export is exactly the work still awaiting a verdict."""
    queued = _make_job(repo, 1)
    labeled = _make_job(repo, 2)
    _make_job(repo, 3, classification="skip")
    repo.update_scraped_job_label(labeled, "skip")

    assert [r["id"] for r in repo.export_rows()] == [queued]


def test_labeling_clears_a_hand_back(repo: Repository):
    """A decided job is no longer 'passed', whichever path decided it."""
    bulk, clicked = _make_job(repo, 1), _make_job(repo, 2)
    repo.labels.mark_passed([_pass(bulk), _pass(clicked)])
    assert len(repo.labels.passed_job_ids()) == 2

    repo.labels.apply_labels([_label(bulk, "skip")])
    repo.update_scraped_job_label(clicked, "skip")

    assert repo.labels.passed_job_ids() == []
    assert _row(repo, bulk)["ai_passed_at"] is None
    assert _row(repo, clicked)["ai_passed_at"] is None
