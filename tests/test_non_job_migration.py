"""Tests for re-evaluating stored emails against the non-job rules."""

from datetime import datetime

import pytest
from jobpilot.classifier.non_job_rules import ACCOUNT_STORAGE, LINKEDIN_SOCIAL
from jobpilot.storage.models import Email, UserFeedback
from jobpilot.storage.non_job_migration import (
    narrow_google_alerts_domain,
    reevaluate_non_job_emails,
)
from jobpilot.storage.repository import Repository

_RECEIVED = datetime(2026, 3, 1, 9, 0)


def _email(email_id: str, subject: str, *, platform: str | None = None, **kwargs) -> Email:
    """Build a stored-looking email; kwargs override any Email field."""
    fields = {
        "id": email_id,
        "thread_id": f"t-{email_id}",
        "sender": "notifications-noreply@linkedin.com",
        "sender_domain": "linkedin.com",
        "subject": subject,
        "received_at": _RECEIVED,
        "platform": platform,
        "processed": True,
        "final_classification": "worth_checking",
        "raw_score": 0.7,
    }
    fields.update(kwargs)
    return Email(**fields)


@pytest.fixture
def seeded(repo: Repository) -> Repository:
    """A repository holding one job email and one social-noise email."""
    repo.insert_email(_email("job1", "Senior Flutter Developer at Proxify", platform="linkedin"))
    repo.insert_email(_email("noise1", "35 people viewed your profile", platform="linkedin"))
    return repo


class TestReevaluation:
    def test_rejects_stored_noise_and_records_the_rule(self, seeded):
        assert reevaluate_non_job_emails(seeded.conn) == 1
        noise = seeded.get_email("noise1")
        assert noise.is_job_related is False
        assert noise.non_job_rule == LINKEDIN_SOCIAL

    def test_leaves_genuine_job_mail_untouched(self, seeded):
        reevaluate_non_job_emails(seeded.conn)
        job = seeded.get_email("job1")
        assert job.is_job_related is True
        assert job.non_job_rule is None

    def test_rejected_email_leaves_the_review_queue(self, seeded):
        before = seeded.count_emails_for_review()
        reevaluate_non_job_emails(seeded.conn)
        assert seeded.count_emails_for_review() == before - 1
        assert [e.id for e in seeded.get_emails_for_review()] == ["job1"]

    def test_rejected_email_is_still_reachable(self, seeded):
        reevaluate_non_job_emails(seeded.conn)
        rejected = seeded.get_emails_not_job_related()
        assert [e.id for e in rejected] == ["noise1"]
        assert rejected[0].non_job_rule == LINKEDIN_SOCIAL

    @pytest.mark.parametrize("label", ["worth_checking", "skip"])
    def test_a_human_calling_it_a_job_outranks_the_rule(self, seeded, label):
        seeded.insert_feedback(UserFeedback(id=None, email_id="noise1", label=label))
        assert reevaluate_non_job_emails(seeded.conn) == 0
        assert seeded.get_email("noise1").is_job_related is True

    def test_a_not_a_job_label_does_not_block_the_rule(self, seeded):
        """The label is a veto, never evidence — a rule still had to match alone."""
        seeded.insert_feedback(UserFeedback(id=None, email_id="noise1", label="not_a_job"))
        assert reevaluate_non_job_emails(seeded.conn) == 1
        assert seeded.get_email("noise1").is_job_related is False

    def test_never_promotes_a_rejected_row_back(self, repo):
        """An email rejected by the old LinkedIn-only check stays rejected."""
        repo.insert_email(_email("old", "Ivan is celebrating 5 years", platform="linkedin"))
        repo.update_email_not_job_related("old")
        reevaluate_non_job_emails(repo.conn)
        assert repo.get_email("old").is_job_related is False

    def test_extraction_outranks_rejection(self, repo):
        """A digest that yielded jobs is kept even when its subject reads as noise."""
        repo.insert_email(_email(
            "digest", "Welcome to Wellfound!",
            platform="wellfound", sender="hi@wellfound.com",
            sender_domain="hi.wellfound.com",
        ))
        repo.insert_scraped_job(_scraped_job("digest"))
        assert reevaluate_non_job_emails(repo.conn) == 0
        assert repo.get_email("digest").is_job_related is True

    def test_is_idempotent(self, seeded):
        reevaluate_non_job_emails(seeded.conn)
        assert reevaluate_non_job_emails(seeded.conn) == 1  # same row, same verdict
        assert seeded.get_email("noise1").non_job_rule == LINKEDIN_SOCIAL

    def test_rejects_a_non_ascii_subject_from_an_unknown_platform(self, repo):
        repo.insert_email(_email(
            "ru", "⚠️ Хранилище Gmail заполнено на 88 %",
            sender="no-reply@google.com", sender_domain="google.com",
        ))
        reevaluate_non_job_emails(repo.conn)
        assert repo.get_email("ru").non_job_rule == ACCOUNT_STORAGE


class TestGoogleAlertsNarrowing:
    def test_swaps_the_domain_for_the_alerts_sender(self, repo):
        repo.insert_preference("monitored_domain", "google.com")
        narrow_google_alerts_domain(repo.conn)
        domains = repo.get_active_domains()
        assert "google.com" not in domains
        assert "googlealerts-noreply@google.com" in domains

    def test_does_nothing_when_the_domain_is_absent(self, repo):
        """A fresh database is seeded with the narrowed sender already; leave it be."""
        before = repo.get_active_domains()
        assert "google.com" not in before
        narrow_google_alerts_domain(repo.conn)
        assert repo.get_active_domains() == before


def _scraped_job(email_id: str):
    """One extracted job linked to an email, enough for the num_jobs count."""
    from jobpilot.storage.models import ScrapedJob

    return ScrapedJob(
        id=None, email_id=email_id, title="Flutter Developer",
        company="Acme", url=f"https://example.com/{email_id}", source="wellfound",
    )


def test_placeholder_count_matches_the_label_tuple():
    """Adding a label to the veto tuple must not desync from the query's placeholders.

    The SQL cannot be built by interpolation (CLAUDE.md: no f-strings in SQL), so
    the pairing is guarded here instead of at runtime.
    """
    from jobpilot.storage.non_job_migration import (
        _LABELS_ASSERTING_JOB,
        _REEVALUATE_SQL,
    )

    placeholders = _REEVALUATE_SQL.split("label IN (")[1].split(")")[0]
    assert placeholders.count("?") == len(_LABELS_ASSERTING_JOB)
