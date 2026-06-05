"""Tests for the storage layer."""

from datetime import datetime

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
