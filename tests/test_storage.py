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
