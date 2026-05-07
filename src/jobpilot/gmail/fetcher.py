"""Email fetching and sync logic."""

import logging
from datetime import datetime, timedelta

from jobpilot.classifier.job_detector import JobDetector
from jobpilot.gmail.client import GmailClient
from jobpilot.gmail.digest import extract_single_job_url, parse_digest
from jobpilot.gmail.parser import parse_message
from jobpilot.storage.models import Email
from jobpilot.storage.repository import Repository

log = logging.getLogger(__name__)

# Sender domains to monitor via Gmail search
MONITORED_DOMAINS = [
    "linkedin.com",
    "e.linkedin.com",
    "wellfound.com",
    "angel.co",
    "relocate.me",
    "arc.dev",
    "toptal.com",
    "turing.com",
    "google.com",
    "indeed.com",
    "indeedmail.com",
    "hired.com",
    "glassdoor.com",
    "stackoverflow.com",
    "stackoverflowmail.com",
    "landing.jobs",
    "arbeitnow.com",
    "toughbyte.com",
    "agilesearch.io",
    "nederlia.com",
    "substack.com",
]


def build_gmail_query(since: datetime | None = None) -> str:
    """Build a Gmail search query for job platform emails."""
    domain_parts = [f"from:{d}" for d in MONITORED_DOMAINS]
    query = f"({' OR '.join(domain_parts)})"
    if since:
        query += f" after:{since.strftime('%Y/%m/%d')}"
    return query


def fetch_new_emails(
    client: GmailClient,
    repo: Repository,
    since: datetime | None = None,
    max_results: int = 200,
) -> int:
    """Fetch new emails from Gmail, parse and store them. Returns count of new emails."""
    if since is None:
        since = datetime.now() - timedelta(days=7)

    query = build_gmail_query(since)
    log.info("Fetching emails with query: %s", query)

    message_stubs = client.list_messages(query, max_results=max_results)
    log.info("Found %d messages matching query", len(message_stubs))

    detector = JobDetector()
    new_count = 0
    for stub in message_stubs:
        msg_id = stub["id"]

        # Skip if already in DB
        if repo.get_email(msg_id):
            continue

        raw = client.get_message(msg_id)
        email = parse_message(raw)

        # Parse digest emails into individual jobs (before insert so we have count)
        extracted_jobs = parse_digest(email)

        # Detect if this is a job opportunity or platform noise
        is_job, confidence = detector.is_job_opportunity(
            email.subject, email.sender, email.platform,
            email.body_text, len(extracted_jobs),
        )
        email.is_job_related = is_job
        email.confidence = confidence

        repo.insert_email(email)

        # Store extracted signals
        for signal in email._signals:
            repo.insert_signal(signal)

        for job in extracted_jobs:
            repo.insert_scraped_job(job)

        # For non-digest emails, extract single job URL for "Open Origin"
        if not extracted_jobs:
            origin_url = extract_single_job_url(email.body_text or "", email.platform)
            if origin_url:
                repo.update_email_origin_url(msg_id, origin_url)

        new_count += 1
        log.debug("Stored email %s: %s (%d jobs extracted)", msg_id, email.subject, len(extracted_jobs))

    log.info("Fetched %d new emails (%d skipped as duplicates)", new_count, len(message_stubs) - new_count)
    return new_count
