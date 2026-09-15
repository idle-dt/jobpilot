"""Tests for the JobDetector whitelist and non-job rejection rules."""

import pytest
from jobpilot.classifier.job_detector import NON_JOB_CONFIDENCE, JobDetector
from jobpilot.classifier.non_job_rules import (
    ACCOUNT_SECURITY,
    ACCOUNT_STORAGE,
    ALERT_ACTIVATION,
    LINKEDIN_SOCIAL,
    PLATFORM_ONBOARDING,
    SERVICE_NOTICE,
    SUBSCRIPTION_CHANGE,
)


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
        assert is_job is False  # onboarding nudge, not a job


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
    def test_unrecognised_subject_is_kept_for_review(self, detector):
        is_job, conf = detector.is_job_opportunity(
            "A note about your account manager", "hello@toughbyte.com", "toughbyte"
        )
        assert is_job is True
        assert conf == 0.0


# Real subjects drawn from the stored corpus, paired with the rule that must fire.
# See SPEC_non_job_email_detection.md: a rule set built from four known subjects
# overfits to them, so the corpus covers every rule and both alphabets.
REJECTED_CORPUS = [
    ("I want to connect", "linkedin", LINKEDIN_SOCIAL),
    ("Your profile is popular - 16 search appearances", "linkedin", LINKEDIN_SOCIAL),
    ("A Recruiter looked at your profile", "linkedin", LINKEDIN_SOCIAL),
    ("35 people viewed your profile", "linkedin", LINKEDIN_SOCIAL),
    ("You appeared in 3 searches", "linkedin", LINKEDIN_SOCIAL),
    ("You have 2 new invitations", "linkedin", LINKEDIN_SOCIAL),
    ("Denys, you got 100+ post impressions. Now what?", "linkedin", LINKEDIN_SOCIAL),
    ("Denys, your profile photo was changed", "linkedin", LINKEDIN_SOCIAL),
    ("Olha Svitelska sent you a message 3 days ago", "linkedin", LINKEDIN_SOCIAL),
    ("Оповещение системы безопасности", None, ACCOUNT_SECURITY),
    ("Denys, here's your PIN 530710", "linkedin", ACCOUNT_SECURITY),
    (
        "Action Required: Verify Your Account Email to Use Wellfound",
        "wellfound",
        ACCOUNT_SECURITY,
    ),
    ("⚠️ Хранилище Gmail заполнено на 88 %", "google_alerts", ACCOUNT_STORAGE),
    (
        "Вы больше не можете загружать новые фотографии и видео",
        "google_alerts",
        ACCOUNT_STORAGE,
    ),
    (
        "Новые настройки конфиденциальности для сервисов Поиска",
        "google_alerts",
        SERVICE_NOTICE,
    ),
    (
        "[Action Advised] Ensure you trust all Google Trust Services Root CAs",
        "google_alerts",
        SERVICE_NOTICE,
    ),
    ("Your Glassdoor and Indeed profiles are now synced", "glassdoor", SERVICE_NOTICE),
    ("Welcome to Turing! 🚀", "turing", PLATFORM_ONBOARDING),
    (
        "Upload your resume to be eligible for Turing roles",
        "turing",
        PLATFORM_ONBOARDING,
    ),
    ("Arc | Complete vetting to get hired 2x faster", "arc_dev", PLATFORM_ONBOARDING),
    (
        "Just a few more steps! Complete your profile and start connecting.",
        "wellfound",
        PLATFORM_ONBOARDING,
    ),
    ("Our top tips to make an all-star profile.", "wellfound", PLATFORM_ONBOARDING),
    ("You’re unsubscribed.", None, SUBSCRIPTION_CHANGE),
    ("Your job alert in remote is now active", "indeed", ALERT_ACTIVATION),
    ("Din jobbevakning för flutter är nu aktiv", "indeed", ALERT_ACTIVATION),
    ("Je vacature-alert voor mobile engineer is nu actief", "indeed", ALERT_ACTIVATION),
]

# Genuine job mail from the same corpus. None of it may be rejected — a phrase
# that reads as noise inside one of these subjects is a pattern that is too broad.
KEPT_CORPUS = [
    ("Senior Flutter Developer at Proxify", "linkedin"),
    ("Message replied: Exciting opportunity at Intellias", "linkedin"),
    ("Software Engineer - Frontend - Payments at Kraken", "linkedin"),
    ("Senior Client Engineer - Core Experience (Formats & Foundations) at Spotify", "linkedin"),
    ("Tech Lead inom mobila lösningar at CGI", "linkedin"),
    ("Androidutvecklare at Bokadirekt", "linkedin"),
    ("New jobs in Amsterdam. Apply Now.", "glassdoor"),
    ("CSA Engineer at KCM Recruitment and 11 more jobs in Oslo for you. Apply Now.", "glassdoor"),
    ("Job at Target,Sandisk,HireVue, Inc. is still available. Apply Soon.", "glassdoor"),
    ("How is your Flutter Engineer job search going?", "glassdoor"),
    ("Java Developer @ Playtech", "indeed"),
    ("Weekly Hand-Curated Tech Jobs With Relocation: Week 62", None),
    ("Denys, are you still interested in these jobs?", "wellfound"),
    ("How do you know if a startup is the right fit for you? We have some pointers.", "wellfound"),
    ("Denys, looking for a new job?", "linkedin"),
    ("See hiring trends for Moneybird", "linkedin"),
]


class TestNonJobRejection:
    @pytest.mark.parametrize(("subject", "platform", "rule"), REJECTED_CORPUS)
    def test_rejects_with_named_rule(self, detector, subject, platform, rule):
        result = detector.classify(subject, "noreply@example.com", platform)
        assert result.is_job is False
        assert result.non_job_rule == rule
        assert result.confidence == NON_JOB_CONFIDENCE

    @pytest.mark.parametrize(("subject", "platform"), KEPT_CORPUS)
    def test_keeps_genuine_job_mail(self, detector, subject, platform):
        result = detector.classify(subject, "noreply@example.com", platform)
        assert result.is_job is True
        assert result.non_job_rule is None

    def test_rejection_is_not_linkedin_specific(self, detector):
        """The same rule fires for a sender that has no platform at all."""
        result = detector.classify(
            "⚠️ Хранилище Gmail заполнено на 88 %", "no-reply@google.com", None
        )
        assert result.is_job is False
        assert result.non_job_rule == ACCOUNT_STORAGE

    def test_social_rule_is_scoped_to_linkedin(self, detector):
        """"Viewed your profile" is recruiter noise on LinkedIn, not elsewhere."""
        assert detector.classify("Someone viewed your profile", "a@b.com", "indeed").is_job

    def test_extraction_outranks_rejection(self, detector):
        """A digest that yielded jobs is kept even when its subject reads as noise."""
        result = detector.classify(
            "Welcome to Wellfound!", "hi@wellfound.com", "wellfound",
            num_extracted_jobs=8,
        )
        assert result.is_job is True
        assert result.confidence == 0.9
        assert result.non_job_rule is None

    def test_whitelist_outranks_rejection(self, detector):
        """Google Alerts wins over the sender's account-mail patterns."""
        is_job, conf = detector.is_job_opportunity(
            "Google Alert - flutter developer", "alerts@google.com", None
        )
        assert is_job is True
        assert conf == 1.0
