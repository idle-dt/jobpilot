"""Tests for deciding identical postings once.

The line these defend: if two rows hold byte-identical posting text, one run must not
leave them with two different verdicts — and must never reach a copy by writing over a
decision the user already made, or one they cancelled.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from jobpilot.services.label_service import LabelBatchService
from jobpilot.storage.duplicate_repo import (
    DUPLICATE_OF_KEY,
    MIN_GROUPED_DESCRIPTION,
)
from jobpilot.storage.label_repo import (
    ASSISTANT_SOURCE,
    PASSED,
    REASON_ALREADY_LABELED,
    REASON_PREVIOUSLY_REJECTED,
    USER_SOURCE,
    LabelEntry,
)
from jobpilot.storage.models import ScrapedJob
from jobpilot.storage.repository import Repository

DEFAULT_MIN_CONFIDENCE = 0.95
WORTH_CHECKING = "worth_checking"
SKIP = "skip"
SHARED_REASON = "Hybrid: 3 days in office"
LONG_TEXT = "We are hiring a mobile engineer. " * 30
SHORT_TEXT = "Mobile engineer wanted in Berlin. " * 4


def _make_job(
    repo: Repository, n: int, description: str | None = None, title: str | None = None,
) -> int:
    """Insert a scraped job with a description and return its id.

    ``insert_scraped_job`` carries neither description nor classification, so both are
    set directly — the review queue is defined by the classification.
    """
    repo.insert_scraped_job(ScrapedJob(
        id=None, source="linkedin", title=title or f"Mobile Engineer {n}",
        url=f"https://example.com/job/{n}", company="Acme", location="Remote",
    ))
    job_id = repo.conn.execute(
        "SELECT id FROM scraped_jobs WHERE url = ?", (f"https://example.com/job/{n}",)
    ).fetchone()["id"]
    repo.conn.execute(
        "UPDATE scraped_jobs SET description = ?, classification = ? WHERE id = ?",
        (description, WORTH_CHECKING, job_id),
    )
    repo.conn.commit()
    return job_id


def _row(repo: Repository, job_id: int) -> sqlite3.Row:
    """Return the verdict columns of one job."""
    return repo.conn.execute(
        "SELECT user_label, label_source, label_reason, ai_passed_at"
        " FROM scraped_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()


@pytest.fixture
def service(repo: Repository, tmp_path: Path) -> LabelBatchService:
    """Batch service writing its audit logs into the test's tmp dir."""
    return LabelBatchService(repo, tmp_path / "logs")


@pytest.fixture
def trio(repo: Repository) -> list[int]:
    """Three unlabeled rows sharing one long, byte-identical description."""
    return [_make_job(repo, n, LONG_TEXT) for n in (1, 2, 3)]


def _run(service, tmp_path, entries, **kwargs):
    """Write a JSONL file of entries and run a batch over it."""
    path = tmp_path / "labels.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return service.run_batch(
        path, kwargs.pop("min_confidence", DEFAULT_MIN_CONFIDENCE), **kwargs
    )


def _entry(job_id: int, label: str = SKIP) -> dict:
    """One confident input entry for a job."""
    return {"id": job_id, "label": label, "confidence": 0.97, "reason": SHARED_REASON}


# --- Grouping ---


def test_identical_long_descriptions_form_one_group(repo: Repository, trio):
    """Lowest id represents; the other two are its members."""
    assert repo.duplicate_groups() == {trio[0]: trio[1:]}


def test_short_shared_description_is_never_grouped(repo: Repository):
    """A stub repeats across unrelated postings, so it is not evidence."""
    assert len(SHORT_TEXT) < MIN_GROUPED_DESCRIPTION
    _make_job(repo, 1, SHORT_TEXT)
    _make_job(repo, 2, SHORT_TEXT)

    assert repo.duplicate_groups() == {}


def test_missing_descriptions_never_group_however_alike_the_titles(repo: Repository):
    """Absent text is not identical text."""
    _make_job(repo, 1, None, title="Flutter Engineer")
    _make_job(repo, 2, None, title="Flutter Engineer")

    assert repo.duplicate_groups() == {}


def test_same_title_and_company_with_different_text_is_not_a_group(repo: Repository):
    """The same role in three cities may be three genuine openings."""
    _make_job(repo, 1, LONG_TEXT + " Berlin office.", title="Flutter Engineer")
    _make_job(repo, 2, LONG_TEXT + " Munich office.", title="Flutter Engineer")

    assert repo.duplicate_groups() == {}


# --- Export ---


def test_export_shows_one_row_per_group_naming_its_copies(repo: Repository, trio):
    """One text, one row to read, with the copies it stands in for named on it."""
    rows = repo.export_rows()

    assert [row["id"] for row in rows] == [trio[0]]
    assert rows[0][DUPLICATE_OF_KEY] == trio[1:]


def test_an_ungrouped_row_carries_no_duplicate_key(repo: Repository):
    """The field appears only where it means something."""
    _make_job(repo, 1, LONG_TEXT)

    assert DUPLICATE_OF_KEY not in repo.export_rows()[0]


def test_a_decided_representative_does_not_hide_its_undecided_copies(
    repo: Repository, trio,
):
    """The lowest id is already labeled, so the queue still shows the text once."""
    repo.update_scraped_job_label(trio[0], SKIP)

    rows = repo.export_rows()

    assert [row["id"] for row in rows] == [trio[1]]
    assert rows[0][DUPLICATE_OF_KEY] == [trio[2]]


# --- Fan-out ---


def test_one_verdict_reaches_every_copy(repo: Repository, service, tmp_path, trio):
    """Labeling the representative decides the whole group, reason included."""
    run = _run(service, tmp_path, [_entry(trio[0])])

    for job_id in trio:
        row = _row(repo, job_id)
        assert (row["user_label"], row["label_source"]) == (SKIP, ASSISTANT_SOURCE)
        assert row["label_reason"] == SHARED_REASON
    assert (run.applied, run.covered, run.rejected) == (1, 2, 0)


def test_an_entry_naming_a_copy_still_decides_the_group(
    repo: Repository, service, tmp_path, trio,
):
    """Fan-out keys on membership, not on which id the input happened to name."""
    run = _run(service, tmp_path, [_entry(trio[2])])

    assert [_row(repo, job_id)["user_label"] for job_id in trio] == [SKIP] * 3
    assert (run.applied, run.covered) == (1, 2)


def test_a_copy_the_user_already_labeled_is_left_exactly_as_it_is(
    repo: Repository, service, tmp_path, trio,
):
    """A fanned-out write never overwrites a decision."""
    repo.update_scraped_job_label(trio[1], WORTH_CHECKING)

    run = _run(service, tmp_path, [_entry(trio[0])])

    kept = _row(repo, trio[1])
    assert (kept["user_label"], kept["label_source"]) == (WORTH_CHECKING, USER_SOURCE)
    assert _row(repo, trio[2])["user_label"] == SKIP
    assert (run.applied, run.covered, run.members_refused) == (1, 1, 1)


def test_a_copy_carrying_its_own_cancel_is_refused_alone(
    repo: Repository, service, tmp_path, trio,
):
    """A fanned-out write never bypasses a cancel."""
    repo.labels.rejections.record(trio[1], SKIP, ASSISTANT_SOURCE, SHARED_REASON)

    run = _run(service, tmp_path, [_entry(trio[0])])

    assert _row(repo, trio[1])["user_label"] is None
    assert [_row(repo, job_id)["user_label"] for job_id in (trio[0], trio[2])] == [SKIP] * 2
    assert (run.covered, run.members_refused, run.conflicts) == (1, 1, [trio[1]])


def test_force_overrides_a_label_on_a_copy_but_never_a_cancel(
    repo: Repository, service, tmp_path, trio,
):
    """Force is about labels; the user's cancel outranks it here as everywhere."""
    repo.labels.rejections.record(trio[1], SKIP, ASSISTANT_SOURCE, SHARED_REASON)
    repo.update_scraped_job_label(trio[2], WORTH_CHECKING)

    run = _run(service, tmp_path, [_entry(trio[0])], force=True)

    assert _row(repo, trio[1])["user_label"] is None
    assert _row(repo, trio[2])["user_label"] == SKIP
    assert (run.covered, run.members_refused) == (1, 1)


def test_a_second_entry_on_the_same_group_cannot_split_it(
    repo: Repository, service, tmp_path, trio,
):
    """The first verdict wins the whole group; the second is refused, not written."""
    run = _run(service, tmp_path, [_entry(trio[0]), _entry(trio[1], WORTH_CHECKING)])

    assert [_row(repo, job_id)["user_label"] for job_id in trio] == [SKIP] * 3
    assert (run.applied, run.rejected, run.covered) == (1, 1, 2)
    logged = [json.loads(line) for line in run.log_path.read_text().splitlines()]
    refused = [e for e in logged if e["outcome"] == "rejected"]
    assert [e["reason"] for e in refused] == [REASON_ALREADY_LABELED]


def test_a_handed_back_copy_is_written_and_its_hand_back_cleared(
    repo: Repository, service, tmp_path, trio,
):
    """The copy is decided now, so 'a run passed on this' is no longer true."""
    repo.labels.mark_passed([
        LabelEntry(job_id=trio[1], label=PASSED, confidence=0.4, reason="no work mode"),
    ])

    run = _run(service, tmp_path, [_entry(trio[0])])

    row = _row(repo, trio[1])
    assert (row["user_label"], row["ai_passed_at"]) == (SKIP, None)
    assert run.covered == 2


def test_a_dry_run_counts_the_copies_and_writes_nothing(
    repo: Repository, service, tmp_path, trio,
):
    """The same decisions, none of them written."""
    run = _run(service, tmp_path, [_entry(trio[0])], dry_run=True)

    assert [_row(repo, job_id)["user_label"] for job_id in trio] == [None] * 3
    assert (run.applied, run.covered) == (1, 2)


# --- Coverage and the audit trail ---


def test_copies_account_for_the_rows_the_input_never_named(
    repo: Repository, service, tmp_path, trio,
):
    """Every queue row is accounted for though the input held one entry."""
    run = _run(service, tmp_path, [_entry(trio[0])])

    assert (run.queue_size, run.unaccounted) == (3, [])


def test_a_copy_that_is_never_written_shows_up_as_unaccounted(
    repo: Repository, service, tmp_path,
):
    """Coverage is the check on this feature: a row below the grouping bar stays visible."""
    ids = [_make_job(repo, n, SHORT_TEXT) for n in (1, 2)]

    run = _run(service, tmp_path, [_entry(ids[0])])

    assert run.unaccounted == [ids[1]]


def test_each_copy_is_logged_with_the_entry_it_came_from(
    repo: Repository, service, tmp_path, trio,
):
    """The trail shows why a row nobody labeled by name has a label."""
    run = _run(service, tmp_path, [_entry(trio[0])])

    logged = [json.loads(line) for line in run.log_path.read_text().splitlines()]
    by_id = {entry["id"]: entry for entry in logged}
    assert by_id[trio[0]]["via"] is None
    assert [by_id[job_id]["via"] for job_id in trio[1:]] == [trio[0], trio[0]]
    assert [by_id[job_id]["outcome"] for job_id in trio] == ["applied"] * 3


def test_a_refused_copy_is_logged_with_its_own_reason(
    repo: Repository, service, tmp_path, trio,
):
    """A refusal on a copy is counted and reported, and aborts nothing."""
    repo.labels.rejections.record(trio[1], SKIP, ASSISTANT_SOURCE, SHARED_REASON)

    run = _run(service, tmp_path, [_entry(trio[0])])

    logged = [json.loads(line) for line in run.log_path.read_text().splitlines()]
    refused = next(e for e in logged if e["id"] == trio[1])
    assert (refused["outcome"], refused["reason"]) == ("rejected", REASON_PREVIOUSLY_REJECTED)
    assert refused["via"] == trio[0]
