"""Determines if an email is a job opportunity or platform noise."""

import re
from dataclasses import dataclass

from jobpilot.classifier.non_job_rules import match_non_job_rule

# Known job platform domains (for general whitelist rules)
JOB_PLATFORM_DOMAINS = {
    "linkedin.com", "e.linkedin.com", "indeed.com", "indeedmail.com",
    "wellfound.com", "angel.co", "hired.com", "glassdoor.com",
    "relocate.me", "landing.jobs", "arbeitnow.com", "arc.dev",
    "toptal.com", "turing.com", "toughbyte.com", "agilesearch.io",
    "nederlia.com", "stackoverflow.com", "stackoverflowmail.com",
}

# Platform-specific whitelist: subject patterns that definitely indicate a job email
WHITELIST = {
    "linkedin": [
        "job alert for",
        "your job alert",
        "is hiring",
        "is looking for",
        "new job",
        "jobs for you",
        "who's hiring",
        "application viewed",
        "application was viewed",
        "application received",
    ],
    "indeed": [
        "new jobs for",
        "daily job",
        "recommended jobs",
    ],
    "wellfound": [
        "new match",
        "interested in you",
        "new startup",
    ],
    "relocate_me": [
        "new job",
        "visa sponsorship",
        "relocation",
    ],
    "landing_jobs": [
        "new job",
        "visa sponsorship",
        "relocation",
    ],
    "arbeitnow": [
        "new job",
        "visa sponsorship",
        "relocation",
    ],
    "google_alerts": [],  # handled separately (subject starts with "Google Alert")
}

# Regex patterns for Indeed
INDEED_REGEX = re.compile(r"jobs?\s+(?:for|matching|based on)", re.IGNORECASE)


WHITELIST_CONFIDENCE = 1.0
DIGEST_MATCH_CONFIDENCE = 0.9
NON_JOB_CONFIDENCE = 0.8
UNKNOWN_CONFIDENCE = 0.0


@dataclass(frozen=True)
class Detection:
    """The detector's verdict on one email, with the rule that produced it."""

    is_job: bool
    confidence: float
    non_job_rule: str | None = None


class JobDetector:
    """Determines if an email is a job opportunity or platform noise."""

    def classify(
        self,
        subject: str,
        sender: str,
        platform: str | None,
        body_text: str | None = None,
        num_extracted_jobs: int = 0,
    ) -> Detection:
        """Decide whether an email is a job opportunity, and say why if it is not.

        Order matters. A digest that yielded jobs outranks every rejection rule, so
        a job alert whose subject happens to contain a rejected phrase is still kept.
        """
        if self._matches_whitelist(subject, sender, platform):
            return Detection(True, WHITELIST_CONFIDENCE)

        if num_extracted_jobs > 0:
            return Detection(True, DIGEST_MATCH_CONFIDENCE)

        rule = match_non_job_rule(subject, platform)
        if rule:
            return Detection(False, NON_JOB_CONFIDENCE, rule)

        # Unknown — show for review, let user decide
        return Detection(True, UNKNOWN_CONFIDENCE)

    def is_job_opportunity(
        self,
        subject: str,
        sender: str,
        platform: str | None,
        body_text: str | None = None,
        num_extracted_jobs: int = 0,
    ) -> tuple[bool, float]:
        """Returns (is_job, confidence). See classify() for the rule that fired.

        confidence 1.0 = whitelist match, definitely a job
        confidence 0.9 = digest parser found jobs
        confidence 0.8 = a non-job rule matched
        confidence 0.0 = unknown, show for review
        """
        result = self.classify(
            subject, sender, platform, body_text, num_extracted_jobs
        )
        return result.is_job, result.confidence

    def _matches_whitelist(
        self, subject: str, sender: str, platform: str | None
    ) -> bool:
        subject_lower = subject.lower()
        sender_lower = sender.lower()

        # Google Alerts: subject starts with "Google Alert"
        if subject_lower.startswith("google alert"):
            return True

        # Platform-specific patterns
        if platform and platform in WHITELIST:
            for pattern in WHITELIST[platform]:
                if pattern in subject_lower:
                    return True

        # Indeed regex
        if platform == "indeed" and INDEED_REGEX.search(subject_lower):
            return True

        # General: "opportunity" from known job platform domain
        sender_domain = sender_lower.split("@")[-1] if "@" in sender_lower else ""
        if sender_domain in JOB_PLATFORM_DOMAINS:
            if "opportunity" in subject_lower or "position" in subject_lower:
                return True

        return False
