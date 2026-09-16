"""Tests for the History page and the guarded cancel.

The line these defend: a cancel is allowed to remove a label and the Tracker entry it
created, and nothing else. If the user has advanced that application or typed anything
into it, the cancel is refused outright and NOTHING is written — not the label, not the
application, not the rejection record.
"""

import sqlite3

import pytest
from jobpilot.services.cancel_service import REFUSAL_NOT_LABELED, CancelService
from jobpilot.services.history_service import (
    PER_PAGE,
    VIEW_NOT_JOB_RELATED,
    HistoryService,
)
from jobpilot.services.tracker_service import (
    AUTO_TRACKED_FIELDS,
    REFUSAL_ADVANCED,
    REFUSAL_EDITED,
    REFUSAL_HAS_HISTORY,
    REFUSAL_HAS_USER_DATA,
    USER_AUTHORED_FIELDS,
    TrackerService,
)
from jobpilot.storage.label_repo import ASSISTANT_SOURCE, LabelEntry
from jobpilot.storage.models import Email, ScrapedJob
from jobpilot.storage.repository import Repository

WORTH_CHECKING = "worth_checking"


def _make_job(repo: Repository, n: int) -> int:
    """Insert a scraped job in the review queue and return its id."""
    repo.insert_scraped_job(ScrapedJob(
        id=None, source="linkedin", title=f"Senior Android Engineer {n}",
        url=f"https://example.com/job/{n}", company="Acme", location="Stockholm",
    ))
    job_id = repo.conn.execute(
        "SELECT id FROM scraped_jobs WHERE url = ?", (f"https://example.com/job/{n}",)
    ).fetchone()["id"]
    repo.conn.execute(
        "UPDATE scraped_jobs SET classification = 'worth_checking' WHERE id = ?", (job_id,)
    )
    repo.conn.commit()
    return job_id


def _tracked_job(repo: Repository, n: int = 1) -> int:
    """Label a job worth_checking through the UI path, so it gains a Tracker entry."""
    job_id = _make_job(repo, n)
    repo.update_scraped_job_label(job_id, WORTH_CHECKING)
    TrackerService(repo).auto_track_scraped_job(job_id)
    return job_id


def _make_email(repo: Repository, email_id: str, rule: str) -> str:
    """Insert an email and have the ingest rules reject it. Returns its id."""
    from datetime import datetime

    repo.insert_email(Email(
        id=email_id, thread_id=f"t-{email_id}", sender="billing@x.com",
        sender_domain="x.com", subject="Your invoice",
        received_at=datetime(2026, 1, 1, 10, 0, 0), platform="linkedin",
    ))
    repo.update_email_not_job_related(email_id, rule=rule)
    return email_id


def _row(repo: Repository, job_id: int) -> sqlite3.Row:
    """Return the label columns of one job."""
    return repo.conn.execute(
        "SELECT user_label, label_source FROM scraped_jobs WHERE id = ?", (job_id,)
    ).fetchone()


def _rejections(repo: Repository) -> int:
    """Count every recorded cancel."""
    return repo.conn.execute(
        "SELECT COUNT(*) AS c FROM label_rejections"
    ).fetchone()["c"]


def _apps(repo: Repository) -> int:
    """Count tracked applications."""
    return repo.conn.execute("SELECT COUNT(*) AS c FROM applications").fetchone()["c"]


@pytest.fixture
def service(repo: Repository) -> CancelService:
    """Cancel service over the test repository."""
    return CancelService(repo)


# --- A clean cancel ---


def test_cancel_clears_label_untracks_and_records(repo: Repository, service):
    """The whole loop: label gone, Tracker entry gone, verdict recorded."""
    job_id = _tracked_job(repo)
    assert _apps(repo) == 1

    result = service.cancel(job_id, record_rejection=True)

    assert (result.cancelled, result.untracked) == (True, True)
    assert _row(repo, job_id)["user_label"] is None
    assert _apps(repo) == 0
    assert repo.labels.rejections.labels_for(job_id) == {WORTH_CHECKING}


def test_a_cancelled_job_returns_to_the_inbox(repo: Repository, service):
    """It becomes ordinary unlabeled work again."""
    job_id = _tracked_job(repo)

    service.cancel(job_id, record_rejection=True)

    assert job_id in {j.id for j in repo.get_scraped_jobs_for_review(limit=100)}


def test_cancel_deletes_the_status_history_too(repo: Repository, service):
    """delete_application is atomic over both tables."""
    job_id = _tracked_job(repo)
    app = repo.get_application_by_scraped_job_id(job_id)
    repo.conn.execute(
        "INSERT INTO application_status_history (application_id, to_status)"
        " VALUES (?, 'saved')", (app.id,),
    )
    repo.conn.commit()
    # A history row is itself a refusal, so clear it to isolate the deletion behaviour.
    repo.conn.execute("DELETE FROM application_status_history")
    repo.conn.commit()

    service.cancel(job_id, record_rejection=True)

    assert repo.conn.execute(
        "SELECT COUNT(*) AS c FROM application_status_history"
    ).fetchone()["c"] == 0


def test_cancelling_a_skip_touches_no_tracker(repo: Repository, service):
    """Only worth_checking is ever tracked, so cancelling a skip is label-only."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "skip")

    result = service.cancel(job_id, record_rejection=True)

    assert (result.cancelled, result.untracked) == (True, False)
    assert repo.labels.rejections.labels_for(job_id) == {"skip"}


def test_cancelling_an_unlabeled_job_is_refused(repo: Repository, service):
    """There is no verdict to reject."""
    job_id = _make_job(repo, 1)

    result = service.cancel(job_id, record_rejection=True)

    assert (result.cancelled, result.refusal) == (False, REFUSAL_NOT_LABELED)
    assert _rejections(repo) == 0


# --- The data guard: a refusal must write nothing at all ---


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("UPDATE applications SET status = 'applied' WHERE id = ?", REFUSAL_ADVANCED),
        ("UPDATE applications SET notes = 'called the recruiter' WHERE id = ?",
         REFUSAL_HAS_USER_DATA),
        ("UPDATE applications SET contact_name = 'A Recruiter' WHERE id = ?",
         REFUSAL_HAS_USER_DATA),
        ("UPDATE applications SET contact_email = 'a@b.c' WHERE id = ?",
         REFUSAL_HAS_USER_DATA),
        ("UPDATE applications SET offer_salary = '80000' WHERE id = ?",
         REFUSAL_HAS_USER_DATA),
        ("UPDATE applications SET offer_currency = 'EUR' WHERE id = ?",
         REFUSAL_HAS_USER_DATA),
        ("UPDATE applications SET offer_equity = '0.5%' WHERE id = ?",
         REFUSAL_HAS_USER_DATA),
        ("UPDATE applications SET offer_relocation_package = 'yes' WHERE id = ?",
         REFUSAL_HAS_USER_DATA),
        ("UPDATE applications SET offer_notes = 'verbal' WHERE id = ?",
         REFUSAL_HAS_USER_DATA),
        # The auto-filled columns are PATCHable too, so editing one must also refuse.
        # Correcting a company that arrived as 'Unknown' is the likely real case.
        ("UPDATE applications SET company = 'Corrected Ltd' WHERE id = ?", REFUSAL_EDITED),
        ("UPDATE applications SET role_title = 'Corrected Title' WHERE id = ?",
         REFUSAL_EDITED),
        ("UPDATE applications SET location = 'Kyiv' WHERE id = ?", REFUSAL_EDITED),
        ("UPDATE applications SET remote = 1 WHERE id = ?", REFUSAL_EDITED),
        ("UPDATE applications SET salary_range = '90k' WHERE id = ?", REFUSAL_EDITED),
        ("UPDATE applications SET job_url = 'https://corrected.example/1' WHERE id = ?",
         REFUSAL_EDITED),
        ("UPDATE applications SET platform = 'corrected' WHERE id = ?", REFUSAL_EDITED),
    ],
)
def test_a_touched_application_refuses_the_cancel(
    repo: Repository, service, mutation: str, expected: str,
):
    """Everything the user could have typed protects the row."""
    job_id = _tracked_job(repo)
    app = repo.get_application_by_scraped_job_id(job_id)
    repo.conn.execute(mutation, (app.id,))
    repo.conn.commit()

    result = service.cancel(job_id, record_rejection=True)

    assert (result.cancelled, result.refusal) == (False, expected)
    assert _row(repo, job_id)["user_label"] == WORTH_CHECKING
    assert _apps(repo) == 1
    assert _rejections(repo) == 0


def test_untrack_guard_covers_every_editable_column():
    """Every PATCHable column must be guarded, or a cancel could delete a user's edit.

    The two tuples partition ApplicationRepository._UPDATABLE_COLUMNS. Adding a new
    editable column to neither would silently widen the automatic-delete path, which is
    exactly how the company/role_title/location gap got in.
    """
    from jobpilot.storage.app_repo import _UPDATABLE_COLUMNS

    guarded = set(AUTO_TRACKED_FIELDS) | set(USER_AUTHORED_FIELDS)
    assert guarded == set(_UPDATABLE_COLUMNS)
    assert not set(AUTO_TRACKED_FIELDS) & set(USER_AUTHORED_FIELDS)


def test_an_untouched_auto_tracked_row_is_not_seen_as_edited(repo: Repository, service):
    """The comparison must not flag a row auto-tracking itself just wrote."""
    job_id = _tracked_job(repo)

    result = service.cancel(job_id, record_rejection=True)

    assert (result.cancelled, result.refusal) == (True, None)


def test_status_history_refuses_the_cancel(repo: Repository, service):
    """A recorded status change is work the user did, even at status 'saved'."""
    job_id = _tracked_job(repo)
    app = repo.get_application_by_scraped_job_id(job_id)
    repo.conn.execute(
        "INSERT INTO application_status_history (application_id, from_status, to_status)"
        " VALUES (?, 'applied', 'saved')", (app.id,),
    )
    repo.conn.commit()

    result = service.cancel(job_id, record_rejection=True)

    assert (result.cancelled, result.refusal) == (False, REFUSAL_HAS_HISTORY)
    assert _row(repo, job_id)["user_label"] == WORTH_CHECKING
    assert _rejections(repo) == 0


# --- Undo is not a cancel ---


def test_undo_clears_the_label_and_the_orphan(repo: Repository, service):
    """The bug this fixes: undo used to leave an application behind."""
    job_id = _tracked_job(repo)

    result = service.cancel(job_id, record_rejection=False)

    assert result.cancelled is True
    assert _row(repo, job_id)["user_label"] is None
    assert _apps(repo) == 0


def test_undo_records_no_rejection(repo: Repository, service):
    """A misclick must not permanently bar a verdict."""
    job_id = _tracked_job(repo)

    service.cancel(job_id, record_rejection=False)

    assert _rejections(repo) == 0
    assert repo.labels.rejections.labels_for(job_id) == set()


def test_undo_is_still_refused_on_a_touched_application(repo: Repository, service):
    """The data guard does not care which gesture asked."""
    job_id = _tracked_job(repo)
    app = repo.get_application_by_scraped_job_id(job_id)
    repo.conn.execute("UPDATE applications SET notes = 'x' WHERE id = ?", (app.id,))
    repo.conn.commit()

    result = service.cancel(job_id, record_rejection=False)

    assert result.cancelled is False
    assert _row(repo, job_id)["user_label"] == WORTH_CHECKING


# --- End to end with the Phase 1 guard ---


def test_a_cancel_blocks_a_later_run_from_the_same_verdict(repo: Repository, service):
    """The point of recording it: the run cannot repeat the mistake."""
    job_id = _tracked_job(repo)
    service.cancel(job_id, record_rejection=True)

    result = repo.labels.apply_labels([
        LabelEntry(job_id=job_id, label=WORTH_CHECKING, confidence=0.99, reason="mobile"),
    ])

    assert len(result.rejected) == 1
    assert _row(repo, job_id)["user_label"] is None


def test_an_undo_leaves_a_later_run_free(repo: Repository, service):
    """The mirror image: an undo records nothing, so the run may still decide."""
    job_id = _tracked_job(repo)
    service.cancel(job_id, record_rejection=False)

    result = repo.labels.apply_labels([
        LabelEntry(job_id=job_id, label=WORTH_CHECKING, confidence=0.99, reason="mobile"),
    ])

    assert result.rejected == []
    assert _row(repo, job_id)["user_label"] == WORTH_CHECKING


# --- The History page ---


def test_history_lists_labeled_jobs_newest_first(repo: Repository):
    """Ordering uses datetime(), so the two stored timestamp formats sort correctly."""
    older, newer = _make_job(repo, 1), _make_job(repo, 2)
    repo.update_scraped_job_label(older, "skip")
    repo.conn.execute(
        "UPDATE scraped_jobs SET labeled_at = '2026-01-01T10:00:00' WHERE id = ?", (older,)
    )
    repo.update_scraped_job_label(newer, "skip")
    repo.conn.execute(
        "UPDATE scraped_jobs SET labeled_at = '2026-01-01 10:00:01' WHERE id = ?", (newer,)
    )
    repo.conn.commit()

    page = HistoryService(repo).build_page()

    assert [r["id"] for r in page.rows] == [newer, older]


def test_history_filters_by_label(repo: Repository):
    """Each chip narrows to its own verdict."""
    kept, skipped = _make_job(repo, 1), _make_job(repo, 2)
    repo.update_scraped_job_label(kept, WORTH_CHECKING)
    repo.update_scraped_job_label(skipped, "skip")

    page = HistoryService(repo).build_page(view=WORTH_CHECKING)

    assert [r["id"] for r in page.rows] == [kept]
    assert page.total == 1


def test_history_assistant_filter_excludes_hand_clicks(repo: Repository):
    """The audit surface after a bulk run."""
    clicked, bulk = _make_job(repo, 1), _make_job(repo, 2)
    repo.update_scraped_job_label(clicked, "skip")
    repo.labels.apply_labels([
        LabelEntry(job_id=bulk, label="skip", confidence=0.99, reason="iOS only"),
    ])

    page = HistoryService(repo).build_page(view="assistant")

    assert [r["id"] for r in page.rows] == [bulk]
    assert page.rows[0]["label_source"] == ASSISTANT_SOURCE


def test_history_excludes_unlabeled_jobs(repo: Repository):
    """History shows labels in effect, not the queue."""
    _make_job(repo, 1)

    assert HistoryService(repo).build_page().total == 0


def test_an_unknown_view_falls_back(repo: Repository):
    """A junk filter shows everything rather than erroring."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "skip")

    page = HistoryService(repo).build_page(view="../etc/passwd")

    assert page.view == "all"
    assert [r["id"] for r in page.rows] == [job_id]


def test_history_pages(repo: Repository):
    """Paging splits the list and reports where it is."""
    for n in range(PER_PAGE + 3):
        job_id = _make_job(repo, n)
        repo.update_scraped_job_label(job_id, "skip")

    first = HistoryService(repo).build_page(page=1)
    second = HistoryService(repo).build_page(page=2)

    assert (len(first.rows), len(second.rows)) == (PER_PAGE, 3)
    assert (first.pages, first.total) == (2, PER_PAGE + 3)
    assert not {r["id"] for r in first.rows} & {r["id"] for r in second.rows}


def test_page_zero_falls_back_to_the_first(repo: Repository):
    """A nonsense page number never produces a negative offset."""
    job_id = _make_job(repo, 1)
    repo.update_scraped_job_label(job_id, "skip")

    page = HistoryService(repo).build_page(page=0)

    assert (page.page, len(page.rows)) == (1, 1)


# --- Non-job mail ---


def test_not_job_related_view_lists_rejected_mail(repo: Repository):
    """The only surface naming the ingest rule that fired."""
    _make_email(repo, "m1", rule="billing")

    page = HistoryService(repo).build_page(view=VIEW_NOT_JOB_RELATED)

    assert [r["id"] for r in page.rows] == ["m1"]
    assert page.rows[0]["non_job_rule"] == "billing"


def test_restoring_mail_sends_it_back_through_classification(repo: Repository):
    """Clearing processed is what actually re-queues it."""
    _make_email(repo, "m1", rule="billing")

    repo.restore_email("m1")

    row = repo.conn.execute(
        "SELECT is_job_related, processed, non_job_rule FROM emails WHERE id = 'm1'"
    ).fetchone()
    assert (bool(row["is_job_related"]), bool(row["processed"])) == (True, False)
    assert row["non_job_rule"] is None
    assert HistoryService(repo).build_page(view=VIEW_NOT_JOB_RELATED).total == 0


# --- The route ---


@pytest.fixture
def authed_client(client, monkeypatch):
    """A test client that passes the Gmail auth gate."""
    monkeypatch.setattr(
        "jobpilot.gmail.auth.GmailAuth.is_authenticated", lambda self: True
    )
    return client


def test_history_route_renders_a_label(repo: Repository, authed_client):
    """The page reaches the database and shows what it found."""
    job_id = _make_job(repo, 1)
    repo.labels.apply_labels([
        LabelEntry(job_id=job_id, label="skip", confidence=0.99, reason="iOS only"),
    ])

    resp = authed_client.get("/history")

    assert resp.status_code == 200
    assert b"iOS only" in resp.data
    assert b"assistant" in resp.data


def test_cancel_endpoint_removes_the_label(repo: Repository, authed_client):
    """The button wired end to end."""
    job_id = _tracked_job(repo)

    resp = authed_client.post(f"/api/history/cancel/{job_id}")

    assert resp.status_code == 200
    assert _row(repo, job_id)["user_label"] is None
    assert _apps(repo) == 0


def test_cancel_endpoint_reports_a_refusal(repo: Repository, authed_client):
    """A refusal is explained in place, and nothing is written."""
    job_id = _tracked_job(repo)
    app = repo.get_application_by_scraped_job_id(job_id)
    repo.conn.execute("UPDATE applications SET status = 'applied' WHERE id = ?", (app.id,))
    repo.conn.commit()

    resp = authed_client.post(f"/api/history/cancel/{job_id}")

    assert resp.status_code == 200
    assert REFUSAL_ADVANCED.encode() in resp.data
    assert _row(repo, job_id)["user_label"] == WORTH_CHECKING
    assert _rejections(repo) == 0


def test_restore_email_endpoint(repo: Repository, authed_client):
    """Restoring is reachable from the page."""
    _make_email(repo, "abc123def456", rule="billing")

    resp = authed_client.post("/api/history/restore-email/abc123def456")

    assert resp.status_code == 200
    assert bool(repo.conn.execute(
        "SELECT is_job_related FROM emails WHERE id = 'abc123def456'"
    ).fetchone()["is_job_related"]) is True


def test_restore_email_rejects_a_bad_id(authed_client):
    """The email id is validated before it reaches the database."""
    assert authed_client.post("/api/history/restore-email/../../etc").status_code in (400, 404)


def test_a_label_reason_is_escaped(repo: Repository, authed_client):
    """Reasons come from scraped text, so they render as characters, never markup."""
    job_id = _make_job(repo, 1)
    repo.labels.apply_labels([
        LabelEntry(
            job_id=job_id, label="skip", confidence=0.99,
            reason="<script>alert(1)</script>",
        ),
    ])

    resp = authed_client.get("/history")

    assert b"<script>alert(1)</script>" not in resp.data
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in resp.data
