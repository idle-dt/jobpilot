"""Tests for the JobDetector whitelist-based classifier."""

import pytest

from jobpilot.classifier.job_detector import JobDetector


@pytest.fixture
def detector():
    return JobDetector()


class TestWhitelistLinkedIn:
    def test_job_alert(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Your job alert for Flutter Developer", "jobs-noreply@linkedin.com", "linkedin"
        )
        assert is_job is True
        assert conf == 1.0

    def test_is_hiring(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Spotify is hiring a Mobile Engineer", "jobs-noreply@linkedin.com", "linkedin"
        )
        assert is_job is True
        assert conf == 1.0

    def test_application_viewed(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Your application was viewed", "jobs-noreply@linkedin.com", "linkedin"
        )
        assert is_job is True
        assert conf == 1.0

    def test_noise_welcome(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Welcome to LinkedIn!", "notifications-noreply@linkedin.com", "linkedin"
        )
        assert is_job is True
        assert conf == 0.0  # unknown, not whitelisted


class TestWhitelistIndeed:
    def test_new_jobs_for(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "12 new jobs for Flutter Developer in Amsterdam",
            "alert@indeed.com", "indeed"
        )
        assert is_job is True
        assert conf == 1.0

    def test_daily_job(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Your daily job alert", "alert@indeed.com", "indeed"
        )
        assert is_job is True
        assert conf == 1.0

    def test_jobs_matching_regex(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Jobs matching your search", "alert@indeed.com", "indeed"
        )
        assert is_job is True
        assert conf == 1.0

    def test_jobs_based_on_regex(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Jobs based on your profile", "alert@indeed.com", "indeed"
        )
        assert is_job is True
        assert conf == 1.0


class TestWhitelistOtherPlatforms:
    def test_wellfound_new_match(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "You have a new match!", "hello@wellfound.com", "wellfound"
        )
        assert is_job is True
        assert conf == 1.0

    def test_relocate_me_visa(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Jobs with visa sponsorship in Netherlands",
            "jobs@relocate.me", "relocate_me"
        )
        assert is_job is True
        assert conf == 1.0

    def test_landing_jobs_relocation(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Relocation opportunities for you", "hello@landing.jobs", "landing_jobs"
        )
        assert is_job is True
        assert conf == 1.0

    def test_arbeitnow_new_job(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "New job: Flutter Developer", "jobs@arbeitnow.com", "arbeitnow"
        )
        assert is_job is True
        assert conf == 1.0

    def test_google_alert(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Google Alert - Flutter developer jobs",
            "googlealerts-noreply@google.com", "google_alerts"
        )
        assert is_job is True
        assert conf == 1.0


class TestWhitelistGeneral:
    def test_opportunity_from_job_platform(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "New opportunity for you", "recruiter@hired.com", "hired"
        )
        assert is_job is True
        assert conf == 1.0

    def test_position_from_job_platform(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Open position: Senior Engineer", "hello@toughbyte.com", "toughbyte"
        )
        assert is_job is True
        assert conf == 1.0


class TestDigestExtraction:
    def test_extracted_jobs_boost(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Weekly digest", "digest@example.com", None,
            num_extracted_jobs=5
        )
        assert is_job is True
        assert conf == 0.9


class TestUnknown:
    def test_unknown_email(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Verify your email address", "noreply@turing.com", "turing"
        )
        assert is_job is True
        assert conf == 0.0

    def test_profile_notification(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Your profile is popular!", "notifications@linkedin.com", "linkedin"
        )
        assert is_job is True
        assert conf == 0.0

    def test_pin_email(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "Here's your PIN", "security@linkedin.com", "linkedin"
        )
        assert is_job is True
        assert conf == 0.0
