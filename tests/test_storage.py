"""Tests for the storage layer."""

import sqlite3
from datetime import datetime

import pytest
from jobpilot.storage.models import (
    Application,
    Email,
    ExtractedSignal,
    ScrapedJob,
    UserFeedback,
)
from jobpilot.storage.repository import Repository


def test_cleanup_corrupted_wellfound_jobs_deletes_unlabeled(db_conn):
    """Unlabeled Wellfound jobs are deleted for re-parsing; labeled ones survive."""
    from jobpilot.storage.database import _cleanup_corrupted_wellfound_jobs

    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url, user_label) VALUES (?,?,?,?)",
        ("wellfound", "Actively Hiring", "https://wellfound.com/jobs/1-x", None),
    )
    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url, user_label) VALUES (?,?,?,?)",
        ("wellfound", "years of exp", "https://links.wellfound.com/s/c/abc", "skip"),
    )
    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url) VALUES (?,?,?)",
        ("linkedin", "iOS Dev", "https://linkedin.com/jobs/view/9"),
    )
    db_conn.commit()

    deleted = _cleanup_corrupted_wellfound_jobs(db_conn)

    titles = {r["title"] for r in db_conn.execute("SELECT title FROM scraped_jobs")}
    assert "Actively Hiring" not in titles
    assert "years of exp" in titles
    assert "iOS Dev" in titles
    assert deleted == 1


def test_cleanup_corrupted_glassdoor_jobs_deletes_unlabeled(db_conn):
    """Unlabeled Glassdoor jobs are deleted for re-parsing; labeled ones survive."""
    from jobpilot.storage.database import _cleanup_corrupted_glassdoor_jobs

    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url, user_label) VALUES (?,?,?,?)",
        ("glassdoor", "Philadelphia, PA", "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=1", None),
    )
    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url, user_label) VALUES (?,?,?,?)",
        ("glassdoor", "Staff Engineer", "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=2", "skip"),
    )
    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url) VALUES (?,?,?)",
        ("linkedin", "iOS Dev", "https://linkedin.com/jobs/view/9"),
    )
    db_conn.commit()

    deleted = _cleanup_corrupted_glassdoor_jobs(db_conn)

    titles = {r["title"] for r in db_conn.execute("SELECT title FROM scraped_jobs")}
    assert "Philadelphia, PA" not in titles
    assert "Staff Engineer" in titles
    assert "iOS Dev" in titles
    assert deleted == 1


def _glassdoor_job(url: str, label: str | None = None) -> ScrapedJob:
    """Build a Glassdoor ScrapedJob for the same posting at a given URL."""
    return ScrapedJob(
        id=None,
        source="glassdoor",
        title="Software Engineer - AI Trainer",
        company="DataAnnotation",
        location="Stockholm",
        url=url,
        user_label=label,
    )


_GD_URL_1 = "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=1010123850169"
_GD_URL_2 = "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=1010123850111"


def test_insert_glassdoor_duplicate_refreshes_link(repo: Repository, db_conn):
    """A same-content Glassdoor insert refreshes the link instead of adding a row."""
    assert repo.insert_scraped_job(_glassdoor_job(_GD_URL_1)) is True
    # Label the stored job so we can confirm the label survives the refresh.
    job_id = db_conn.execute("SELECT id FROM scraped_jobs").fetchone()["id"]
    repo.update_scraped_job_label(job_id, "skip")

    assert repo.insert_scraped_job(_glassdoor_job(_GD_URL_2)) is False

    rows = db_conn.execute(
        "SELECT url, user_label FROM scraped_jobs WHERE source = 'glassdoor'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["url"] == _GD_URL_2  # link refreshed to the newer digest URL
    assert rows[0]["user_label"] == "skip"  # user's label preserved


def test_insert_glassdoor_duplicate_link_clash_does_not_raise(repo: Repository, db_conn):
    """Refreshing a link must not trip the UNIQUE url constraint when it's taken."""
    assert repo.insert_scraped_job(_glassdoor_job(_GD_URL_1)) is True
    other = _glassdoor_job(_GD_URL_2)
    other.location = "Berlin"  # distinct content, owns _GD_URL_2
    assert repo.insert_scraped_job(other) is True
    # Same content as the first job, but carrying a URL already owned by `other`.
    clash = _glassdoor_job(_GD_URL_2)
    assert repo.insert_scraped_job(clash) is False  # handled, no row added, no raise

    rows = db_conn.execute(
        "SELECT url FROM scraped_jobs WHERE source='glassdoor' ORDER BY id"
    ).fetchall()
    assert [r["url"] for r in rows] == [_GD_URL_1, _GD_URL_2]  # links unchanged


def test_insert_glassdoor_distinct_content_still_inserts(repo: Repository, db_conn):
    """Different content (and a non-Glassdoor row with same content) still inserts."""
    assert repo.insert_scraped_job(_glassdoor_job(_GD_URL_1)) is True
    other = _glassdoor_job(_GD_URL_2)
    other.location = "Berlin"
    assert repo.insert_scraped_job(other) is True
    linkedin = _glassdoor_job("https://linkedin.com/jobs/view/9")
    linkedin.source = "linkedin"
    assert repo.insert_scraped_job(linkedin) is True
    assert db_conn.execute("SELECT COUNT(*) c FROM scraped_jobs").fetchone()["c"] == 3


def test_dedup_glassdoor_jobs_by_content_keeps_labeled_and_freshest_link(db_conn):
    """Migration collapses a content group: keep the labeled row, refresh its link."""
    from jobpilot.storage.database import _dedup_glassdoor_jobs_by_content

    for url, label in ((_GD_URL_1, "skip"), (_GD_URL_2, None), (_GD_URL_2 + "x", None)):
        db_conn.execute(
            "INSERT INTO scraped_jobs (source, title, company, location, url, user_label) "
            "VALUES ('glassdoor', 'SWE', 'DataAnnotation', 'Stockholm', ?, ?)",
            (url, label),
        )
    db_conn.commit()

    deleted = _dedup_glassdoor_jobs_by_content(db_conn)

    rows = db_conn.execute(
        "SELECT url, user_label FROM scraped_jobs WHERE source = 'glassdoor'"
    ).fetchall()
    assert deleted == 2
    assert len(rows) == 1
    assert rows[0]["user_label"] == "skip"  # labeled survivor kept
    assert rows[0]["url"] == _GD_URL_2 + "x"  # link refreshed to newest sibling


def test_dedup_glassdoor_repoints_applications_to_survivor(db_conn):
    """An application on a duplicate row is repointed to the survivor, FK intact."""
    from jobpilot.storage.database import _dedup_glassdoor_jobs_by_content

    cur = db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, company, location, url, user_label) "
        "VALUES ('glassdoor', 'SWE', 'DataAnnotation', 'Stockholm', ?, 'skip')",
        (_GD_URL_1,),
    )
    survivor_id = cur.lastrowid
    cur = db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, company, location, url) "
        "VALUES ('glassdoor', 'SWE', 'DataAnnotation', 'Stockholm', ?)",
        (_GD_URL_2,),
    )
    dupe_id = cur.lastrowid
    db_conn.execute(
        "INSERT INTO applications (company, role_title, scraped_job_id) VALUES (?,?,?)",
        ("DataAnnotation", "SWE", dupe_id),
    )
    db_conn.commit()

    deleted = _dedup_glassdoor_jobs_by_content(db_conn)  # must not raise on FK

    assert deleted == 1
    app_ref = db_conn.execute(
        "SELECT scraped_job_id FROM applications"
    ).fetchone()["scraped_job_id"]
    assert app_ref == survivor_id  # application now points at the survivor
    remaining = db_conn.execute(
        "SELECT id FROM scraped_jobs WHERE source='glassdoor'"
    ).fetchall()
    assert [r["id"] for r in remaining] == [survivor_id]


def _insert_app(
    db_conn,
    *,
    status="saved",
    job_url=None,
    scraped_job_id=None,
    created_at="2024-01-01T00:00:00",
    company="Cognizant",
    role_title="Sr. Flutter Developer",
    location="Warrensville, OH",
):
    """Insert an application with explicit dedup-relevant fields; return its id."""
    cur = db_conn.execute(
        "INSERT INTO applications (company, role_title, location, status, job_url, "
        "scraped_job_id, created_at) VALUES (?,?,?,?,?,?,?)",
        (company, role_title, location, status, job_url, scraped_job_id, created_at),
    )
    return cur.lastrowid


def test_dedup_collapses_identical_applications_and_reroutes_history(db_conn):
    """Same (title, company, location): newest survives, dupe deleted, history rerouted."""
    from jobpilot.storage.database import _dedup_tracked_applications

    dupe_id = _insert_app(db_conn, created_at="2024-01-01T00:00:00")
    survivor_id = _insert_app(db_conn, created_at="2024-02-01T00:00:00")
    db_conn.execute(
        "INSERT INTO application_status_history (application_id, to_status) VALUES (?, 'saved')",
        (dupe_id,),
    )
    db_conn.commit()

    removed = _dedup_tracked_applications(db_conn)

    assert removed == 1
    ids = [r["id"] for r in db_conn.execute("SELECT id FROM applications").fetchall()]
    assert ids == [survivor_id]
    history_ref = db_conn.execute(
        "SELECT application_id FROM application_status_history"
    ).fetchone()["application_id"]
    assert history_ref == survivor_id


def test_dedup_keeps_higher_status_survivor(db_conn):
    """'applied' outranks 'saved' even when the saved row is newer."""
    from jobpilot.storage.database import _dedup_tracked_applications

    applied_id = _insert_app(db_conn, status="applied", created_at="2024-01-01T00:00:00")
    _insert_app(db_conn, status="saved", created_at="2024-02-01T00:00:00")
    db_conn.commit()

    removed = _dedup_tracked_applications(db_conn)

    assert removed == 1
    rows = db_conn.execute("SELECT id, status FROM applications").fetchall()
    assert [r["id"] for r in rows] == [applied_id]
    assert rows[0]["status"] == "applied"


def test_dedup_swaps_dead_survivor_url_for_alive_duplicate(db_conn):
    """Survivor URL dead, duplicate URL alive: survivor's job_url is swapped in."""
    from unittest.mock import patch

    from jobpilot.storage.database import _dedup_tracked_applications

    alive_url = "https://alive.example/job"
    _insert_app(db_conn, job_url=alive_url, created_at="2024-01-01T00:00:00")
    survivor_id = _insert_app(
        db_conn, job_url="https://dead.example/job", created_at="2024-02-01T00:00:00"
    )
    db_conn.commit()

    with patch(
        "jobpilot.storage.database._is_url_alive",
        side_effect=lambda url, *a, **k: url == alive_url,
    ):
        removed = _dedup_tracked_applications(db_conn)

    assert removed == 1
    survivor_url = db_conn.execute(
        "SELECT job_url FROM applications WHERE id = ?", (survivor_id,)
    ).fetchone()["job_url"]
    assert survivor_url == alive_url


def test_dedup_keeps_survivor_url_when_all_dead(db_conn):
    """No reachable URL in the group: the survivor keeps its original job_url."""
    from unittest.mock import patch

    from jobpilot.storage.database import _dedup_tracked_applications

    _insert_app(db_conn, job_url="https://a.example/job", created_at="2024-01-01T00:00:00")
    survivor_id = _insert_app(
        db_conn, job_url="https://b.example/job", created_at="2024-02-01T00:00:00"
    )
    db_conn.commit()

    with patch("jobpilot.storage.database._is_url_alive", return_value=False):
        removed = _dedup_tracked_applications(db_conn)

    assert removed == 1
    survivor_url = db_conn.execute(
        "SELECT job_url FROM applications WHERE id = ?", (survivor_id,)
    ).fetchone()["job_url"]
    assert survivor_url == "https://b.example/job"


def test_dedup_deletes_orphaned_scraped_job(db_conn):
    """The deleted duplicate's scraped_job is removed when nothing else references it."""
    from jobpilot.storage.database import _dedup_tracked_applications

    orphan_id = db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url) VALUES ('email', 'Sr. Flutter Developer', "
        "'https://x.example/1')"
    ).lastrowid
    _insert_app(db_conn, scraped_job_id=orphan_id, created_at="2024-01-01T00:00:00")
    _insert_app(db_conn, created_at="2024-02-01T00:00:00")
    db_conn.commit()

    removed = _dedup_tracked_applications(db_conn)

    assert removed == 1
    assert db_conn.execute(
        "SELECT 1 FROM scraped_jobs WHERE id = ?", (orphan_id,)
    ).fetchone() is None


def test_dedup_keeps_shared_scraped_job(db_conn):
    """A scraped_job still referenced by the survivor is kept after the duplicate is removed."""
    from jobpilot.storage.database import _dedup_tracked_applications

    shared_id = db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url) VALUES ('email', 'Sr. Flutter Developer', "
        "'https://x.example/2')"
    ).lastrowid
    _insert_app(db_conn, scraped_job_id=shared_id, created_at="2024-01-01T00:00:00")
    _insert_app(db_conn, scraped_job_id=shared_id, created_at="2024-02-01T00:00:00")
    db_conn.commit()

    removed = _dedup_tracked_applications(db_conn)

    assert removed == 1
    assert db_conn.execute(
        "SELECT 1 FROM scraped_jobs WHERE id = ?", (shared_id,)
    ).fetchone() is not None


def test_dedup_leaves_unique_application_untouched(db_conn):
    """An application with no content-duplicate is left alone."""
    from jobpilot.storage.database import _dedup_tracked_applications

    app_id = _insert_app(db_conn)
    db_conn.commit()

    removed = _dedup_tracked_applications(db_conn)

    assert removed == 0
    ids = [r["id"] for r in db_conn.execute("SELECT id FROM applications").fetchall()]
    assert ids == [app_id]


def test_dedup_runs_only_once(db_conn):
    """_run_once guards the migration: duplicates added after the first run are not collapsed."""
    from jobpilot.storage.database import _dedup_tracked_applications, _run_once

    _insert_app(db_conn, created_at="2024-01-01T00:00:00")
    _insert_app(db_conn, created_at="2024-02-01T00:00:00")
    key = "_migration_dedup_tracked_applications"
    db_conn.execute("DELETE FROM settings WHERE key = ?", (key,))  # init_db already ran it
    db_conn.commit()

    _run_once(db_conn, key, _dedup_tracked_applications)
    assert db_conn.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"] == 1

    _insert_app(db_conn, created_at="2024-03-01T00:00:00")
    db_conn.commit()
    _run_once(db_conn, key, _dedup_tracked_applications)  # key already set -> no-op
    assert db_conn.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"] == 2


def test_init_db_creates_tables(db_conn):
    """Verify all expected tables are created."""
    cursor = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row["name"] for row in cursor.fetchall()}
    expected = {
        "emails", "extracted_signals", "user_feedback",
        "model_versions", "platform_patterns", "scraped_jobs",
        "applications", "application_status_history",
    }
    assert expected.issubset(tables)


def test_insert_and_get_email(repo: Repository):
    email = Email(
        id="msg_001",
        thread_id="thread_001",
        sender="jobs@linkedin.com",
        sender_domain="linkedin.com",
        subject="New job: Senior Flutter Developer",
        received_at=datetime(2024, 1, 15, 10, 30),
        body_text="We found a job for you...",
        platform="linkedin",
    )
    repo.insert_email(email)
    result = repo.get_email("msg_001")
    assert result is not None
    assert result.subject == "New job: Senior Flutter Developer"
    assert result.platform == "linkedin"
    assert result.sender_domain == "linkedin.com"


def test_insert_duplicate_email_ignored(repo: Repository):
    email = Email(
        id="msg_dup",
        thread_id="thread_dup",
        sender="test@example.com",
        sender_domain="example.com",
        subject="Test",
        received_at=datetime(2024, 1, 1),
    )
    repo.insert_email(email)
    repo.insert_email(email)  # Should not raise
    assert repo.get_email("msg_dup") is not None


def test_update_email_scores(repo: Repository):
    email = Email(
        id="msg_score",
        thread_id="thread_score",
        sender="test@example.com",
        sender_domain="example.com",
        subject="Flutter role in Amsterdam",
        received_at=datetime(2024, 2, 1),
    )
    repo.insert_email(email)
    repo.update_email_scores("msg_score", 0.85, 0.78, "worth_checking", 0.92)

    result = repo.get_email("msg_score")
    assert result.raw_score == 0.85
    assert result.ml_score == 0.78
    assert result.final_classification == "worth_checking"
    assert result.processed is True


def test_insert_and_get_signals(repo: Repository):
    email = Email(
        id="msg_sig",
        thread_id="thread_sig",
        sender="test@example.com",
        sender_domain="example.com",
        subject="Test",
        received_at=datetime(2024, 1, 1),
    )
    repo.insert_email(email)

    signal = ExtractedSignal(id=None, email_id="msg_sig", signal_type="tech_stack", signal_value="flutter")
    repo.insert_signal(signal)

    signals = repo.get_signals_for_email("msg_sig")
    assert len(signals) == 1
    assert signals[0].signal_type == "tech_stack"
    assert signals[0].signal_value == "flutter"


def test_feedback_crud(repo: Repository):
    email = Email(
        id="msg_fb",
        thread_id="thread_fb",
        sender="test@example.com",
        sender_domain="example.com",
        subject="Test",
        received_at=datetime(2024, 1, 1),
    )
    repo.insert_email(email)

    feedback = UserFeedback(id=None, email_id="msg_fb", label="worth_checking", notes="Great role")
    repo.insert_feedback(feedback)

    assert repo.count_feedback() == 1
    all_fb = repo.get_all_feedback()
    assert all_fb[0].label == "worth_checking"
    assert all_fb[0].notes == "Great role"


def test_scraped_job_insert_and_dedup(repo: Repository):
    job = ScrapedJob(
        id=None, source="flutterjobs", title="Flutter Dev",
        url="https://flutterjobs.com/job/123", company="Acme",
        location="Amsterdam", remote=False,
    )
    assert repo.insert_scraped_job(job) is True
    assert repo.insert_scraped_job(job) is False  # duplicate URL


def test_application_lifecycle(repo: Repository):
    app = Application(
        id=None, company="TechCorp", role_title="Senior Flutter Engineer",
        location="Amsterdam", platform="linkedin",
    )
    app_id = repo.insert_application(app)
    assert app_id > 0

    result = repo.get_application(app_id)
    assert result.company == "TechCorp"
    assert result.status == "applied"

    repo.update_application_status(app_id, "screening", notes="Phone screen scheduled")
    result = repo.get_application(app_id)
    assert result.status == "screening"

    history = repo.get_application_history(app_id)
    assert len(history) == 1
    assert history[0].from_status == "applied"
    assert history[0].to_status == "screening"


def test_application_stats(repo: Repository):
    for i, status in enumerate(["applied", "applied", "screening", "offer"]):
        app = Application(
            id=None, company=f"Company{i}", role_title="Dev", status=status,
        )
        repo.insert_application(app)

    stats = repo.count_applications_by_status()
    assert stats["applied"] == 2
    assert stats["screening"] == 1
    assert stats["offer"] == 1


def test_email_stats(repo: Repository):
    email = Email(
        id="msg_stats",
        thread_id="thread_stats",
        sender="test@linkedin.com",
        sender_domain="linkedin.com",
        subject="Job alert",
        received_at=datetime(2024, 3, 1),
        platform="linkedin",
        processed=True,
        final_classification="worth_checking",
    )
    repo.insert_email(email)

    stats = repo.get_email_stats()
    assert stats["total"] == 1
    assert stats["processed"] == 1
    assert stats["by_platform"]["linkedin"] == 1


# --- Duplicate email deduplication ---

_JOB_URL = "https://www.linkedin.com/jobs/view/123"


def _review_email(repo: Repository, email_id: str, **overrides) -> Email:
    """Insert a processed, job-related email eligible for the review queue."""
    fields = dict(
        id=email_id,
        thread_id=f"thread_{email_id}",
        sender="jobs@linkedin.com",
        sender_domain="linkedin.com",
        subject="New job for you",
        received_at=datetime(2024, 5, 1, 9, 0),
        platform="linkedin",
        processed=True,
        is_job_related=True,
        final_classification="worth_checking",
    )
    fields.update(overrides)
    email = Email(**fields)
    repo.insert_email(email)
    return email


def _scraped_job(repo: Repository, url: str, email_id: str | None = None) -> int:
    """Insert a scraped job and return its row id."""
    repo.insert_scraped_job(
        ScrapedJob(id=None, source="email", title="Engineer", url=url, email_id=email_id)
    )
    row = repo.conn.execute(
        "SELECT id FROM scraped_jobs WHERE url = ?", (url,)
    ).fetchone()
    return row["id"]


def test_review_excludes_email_matched_by_origin_url(repo: Repository):
    """A duplicate email (origin_url -> existing scraped job) is excluded from review."""
    _scraped_job(repo, _JOB_URL)
    _review_email(repo, "dup", origin_url=_JOB_URL)

    review_ids = {e.id for e in repo.get_emails_for_review()}
    assert "dup" not in review_ids
    assert repo.count_emails_for_review() == len(repo.get_emails_for_review())


def test_review_keeps_email_with_null_origin_url(repo: Repository):
    """An email with no origin_url is unaffected and appears in the review queue."""
    _review_email(repo, "plain")

    review_ids = {e.id for e in repo.get_emails_for_review()}
    assert "plain" in review_ids


def test_review_excludes_email_with_scraped_email_id(repo: Repository):
    """Existing behavior preserved: email with its own scraped job is excluded."""
    _review_email(repo, "digested")
    _scraped_job(repo, _JOB_URL, email_id="digested")

    review_ids = {e.id for e in repo.get_emails_for_review()}
    assert "digested" not in review_ids


def test_count_matches_review_list_with_duplicate(repo: Repository):
    """count_emails_for_review stays consistent when a duplicate-origin email exists."""
    _scraped_job(repo, _JOB_URL)
    _review_email(repo, "dup", origin_url=_JOB_URL)
    _review_email(repo, "plain")

    assert repo.count_emails_for_review() == len(repo.get_emails_for_review())


def test_count_with_classification_filter_excludes_duplicate(repo: Repository):
    """The classification-filtered count also excludes duplicate-origin emails."""
    _scraped_job(repo, _JOB_URL)
    _review_email(repo, "dup", origin_url=_JOB_URL, final_classification="worth_checking")
    _review_email(repo, "plain", final_classification="worth_checking")

    assert repo.count_emails_for_review(classification="worth_checking") == 1


def test_descriptions_resolved_by_origin_url(repo: Repository):
    """A duplicate email with no scraped row gets its description via origin_url join."""
    job_id = _scraped_job(repo, _JOB_URL)
    repo.update_scraped_job_description(job_id, "Build great things.")
    _review_email(repo, "dup", origin_url=_JOB_URL)

    descriptions = repo.get_descriptions_for_emails(["dup"])
    assert descriptions["dup"][0] == "Build great things."


def test_descriptions_email_id_takes_precedence_over_origin_url(repo: Repository):
    """When both match, the email_id-linked description wins."""
    _review_email(repo, "dup", origin_url=_JOB_URL)
    own = _scraped_job(repo, "https://www.linkedin.com/jobs/view/own", email_id="dup")
    repo.update_scraped_job_description(own, "Own description.")
    other = _scraped_job(repo, _JOB_URL)
    repo.update_scraped_job_description(other, "Origin description.")

    descriptions = repo.get_descriptions_for_emails(["dup"])
    assert descriptions["dup"][0] == "Own description."


# --- Expired status + tracker sort order -------------------------------------

# Pre-change applications schema: status CHECK lacks 'expired' and `remote` is the
# LAST column (as it lands after _apply_column_migrations' ALTER on real DBs). Used
# to exercise the rebuild migration's explicit-column copy on a realistic layout.
_OLD_APPLICATIONS_SQL = """
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT REFERENCES emails(id),
    scraped_job_id INTEGER REFERENCES scraped_jobs(id),
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    location TEXT,
    salary_range TEXT,
    job_url TEXT,
    platform TEXT,
    status TEXT NOT NULL DEFAULT 'applied' CHECK(status IN (
        'saved', 'applied', 'screening', 'technical',
        'onsite', 'offer', 'accepted', 'rejected',
        'withdrawn', 'no_response'
    )),
    applied_at TEXT DEFAULT (datetime('now')),
    last_status_change TEXT DEFAULT (datetime('now')),
    contact_name TEXT,
    contact_email TEXT,
    notes TEXT,
    offer_salary TEXT,
    offer_currency TEXT,
    offer_equity TEXT,
    offer_relocation_package TEXT,
    offer_notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    remote BOOLEAN DEFAULT FALSE
);
"""


def _tracker(repo: Repository):
    from jobpilot.services.tracker_service import TrackerService

    return TrackerService(repo)


def test_update_status_accepts_expired(repo: Repository):
    """update_status persists the new 'expired' status and reports success."""
    app_id = repo.insert_application(
        Application(id=None, company="TechCorp", role_title="Flutter Engineer")
    )
    assert _tracker(repo).update_status(app_id, "expired") is True
    assert repo.get_application(app_id).status == "expired"


def test_create_application_with_expired_status(repo: Repository):
    """Creating an application directly as 'expired' passes the CHECK constraint."""
    app_id = _tracker(repo).create_application(
        company="GoneCorp", role_title="Backend Dev", status="expired"
    )
    assert repo.get_application(app_id).status == "expired"


def test_status_label_for_expired():
    """STATUS_LABELS exposes a human-readable label for the new status."""
    from jobpilot.services.tracker_service import STATUS_LABELS

    assert STATUS_LABELS["expired"] == "Expired"


def test_list_applications_sorted_by_pipeline_stage(repo: Repository):
    """Apps are ordered by pipeline rank: offer, applied, saved, expired, rejected."""
    for status in ("saved", "offer", "rejected", "applied", "expired"):
        repo.insert_application(
            Application(id=None, company=f"Co-{status}", role_title="Dev", status=status)
        )
    apps, _, _ = _tracker(repo).list_applications()
    assert [a.status for a in apps] == ["offer", "applied", "saved", "expired", "rejected"]


def test_list_applications_newest_first_within_status(db_conn, repo: Repository):
    """Within one status, the most recently changed application sorts first."""
    db_conn.execute(
        "INSERT INTO applications (company, role_title, status, last_status_change) "
        "VALUES (?,?,?,?)",
        ("OldCo", "Dev", "applied", "2026-05-01 00:00:00"),
    )
    db_conn.execute(
        "INSERT INTO applications (company, role_title, status, last_status_change) "
        "VALUES (?,?,?,?)",
        ("NewCo", "Dev", "applied", "2026-06-01 00:00:00"),
    )
    db_conn.commit()
    apps, _, _ = _tracker(repo).list_applications()
    assert [a.company for a in apps] == ["NewCo", "OldCo"]


def test_migrate_add_expired_rebuilds_and_preserves_data(db_conn):
    """Migration on an old-schema table preserves all data, history, and enables 'expired'."""
    from jobpilot.storage.database import _migrate_add_expired_status

    db_conn.execute("DROP TABLE applications")
    db_conn.executescript(_OLD_APPLICATIONS_SQL)
    db_conn.execute(
        "INSERT INTO applications (id, company, role_title, status, offer_salary, "
        "created_at, remote) VALUES (1, 'Acme', 'Dev', 'offer', '120k', "
        "'2026-01-01 00:00:00', 1)"
    )
    db_conn.execute(
        "INSERT INTO application_status_history (application_id, to_status) VALUES (1, 'offer')"
    )
    db_conn.commit()

    _migrate_add_expired_status(db_conn)

    row = db_conn.execute("SELECT * FROM applications WHERE id = 1").fetchone()
    assert (row["company"], row["status"], row["offer_salary"]) == ("Acme", "offer", "120k")
    assert row["remote"] == 1 and row["created_at"] == "2026-01-01 00:00:00"
    history = db_conn.execute(
        "SELECT COUNT(*) c FROM application_status_history WHERE application_id = 1"
    ).fetchone()["c"]
    assert history == 1  # FK-off swap did not cascade-delete history
    db_conn.execute("UPDATE applications SET status = 'expired' WHERE id = 1")  # now allowed
    indexes = {
        r["name"]
        for r in db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='applications'"
        )
    }
    assert "idx_applications_status" in indexes  # indexes recreated after rebuild


def test_migrate_add_expired_rolls_back_on_failure(db_conn, monkeypatch):
    """A failure mid-rebuild rolls back, leaving the original table and data intact."""
    from jobpilot.storage import database as db_module
    from jobpilot.storage.database import _migrate_add_expired_status

    db_conn.execute("DROP TABLE applications")
    db_conn.executescript(_OLD_APPLICATIONS_SQL)
    db_conn.execute(
        "INSERT INTO applications (id, company, role_title, status) VALUES (1, 'Acme', 'Dev', 'offer')"
    )
    db_conn.commit()

    # Inject a statement that errors after the table swap but before COMMIT.
    broken = db_module._APPLICATIONS_REBUILD_SQL.replace(
        "COMMIT;", "INSERT INTO applications (nonexistent) VALUES (1);\nCOMMIT;"
    )
    monkeypatch.setattr(db_module, "_APPLICATIONS_REBUILD_SQL", broken)
    with pytest.raises(sqlite3.OperationalError):
        _migrate_add_expired_status(db_conn)
    db_conn.rollback()  # discard the failed, uncommitted transaction

    row = db_conn.execute("SELECT company, status FROM applications WHERE id = 1").fetchone()
    assert (row["company"], row["status"]) == ("Acme", "offer")  # original survived


def test_migrate_add_expired_is_idempotent(db_conn):
    """Re-running the migration on an already-migrated table is a harmless no-op."""
    from jobpilot.storage.database import _migrate_add_expired_status

    db_conn.execute(
        "INSERT INTO applications (id, company, role_title, status) VALUES (5, 'Keep', 'Dev', 'saved')"
    )
    db_conn.commit()
    _migrate_add_expired_status(db_conn)  # SCHEMA_SQL already has 'expired' -> guard returns early
    assert db_conn.execute(
        "SELECT company FROM applications WHERE id = 5"
    ).fetchone()["company"] == "Keep"
