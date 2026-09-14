"""Email fetching and sync logic."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from googleapiclient.errors import HttpError

from jobpilot.classifier.job_detector import JobDetector
from jobpilot.gmail.client import GmailClient, GmailQuotaExhaustedError
from jobpilot.gmail.digest import extract_single_job_url, parse_digest
from jobpilot.gmail.parser import parse_message
from jobpilot.storage.models import Email, ExtractedSignal, ScrapedJob
from jobpilot.storage.repository import Repository

log = logging.getLogger(__name__)


# Gmail's quota metric is "Units per minute per user", so a spent budget refills within a
# minute. On exhaustion the fetch pauses for one window and resumes rather than giving up.
_QUOTA_WINDOW_SECONDS = 60.0
# Bounds the added wall-clock time so one sync cannot run indefinitely on a large backlog.
_MAX_QUOTA_WAITS = 3


@dataclass
class FetchResult:
    """Outcome of a Gmail fetch pass."""

    new_emails: int
    truncated: bool  # True when the quota cut the batch short even after waiting
    processed: int = 0  # Message stubs consumed: stored, already-known, or skipped as bad
    total: int = 0  # Message stubs the query matched

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


def build_gmail_query(
    since: datetime | None = None, domains: list[str] | None = None,
) -> str:
    """Build a Gmail search query for job platform emails."""
    active_domains = domains or MONITORED_DOMAINS
    domain_parts = [f"from:{d}" for d in active_domains]
    query = f"({' OR '.join(domain_parts)})"
    if since:
        query += f" after:{since.strftime('%Y/%m/%d')}"
    return query


def fetch_new_emails(
    client: GmailClient,
    repo: Repository,
    since: datetime | None = None,
    max_results: int = 200,
    sleep: Callable[[float], None] = time.sleep,
    on_quota_wait: Callable[[int, int], None] | None = None,
) -> FetchResult:
    """Fetch new emails from Gmail, parse and store them.

    A quota limit pauses the fetch and resumes, so a normal run handles every matched
    message; only a quota still exhausted after _MAX_QUOTA_WAITS pauses returns truncated.
    `sleep` is injectable so tests do not wait on a real quota window; `on_quota_wait` is
    called with (processed, total) before each pause.
    """
    if since is None:
        since = datetime.now() - timedelta(days=7)

    active_domains = repo.get_active_domains() or None
    query = build_gmail_query(since, domains=active_domains)
    log.info("Fetching emails with query: %s", query)

    try:
        message_stubs = client.list_messages(query, max_results=max_results)
    except GmailQuotaExhaustedError:
        log.warning("Gmail quota exhausted while listing messages; nothing fetched")
        return FetchResult(new_emails=0, truncated=True, processed=0, total=0)
    log.info("Found %d messages matching query", len(message_stubs))

    return _fetch_with_resume(message_stubs, client, repo, sleep, on_quota_wait)


def _fetch_with_resume(
    stubs: list[dict],
    client: GmailClient,
    repo: Repository,
    sleep: Callable[[float], None],
    on_quota_wait: Callable[[int, int], None] | None,
) -> FetchResult:
    """Process every stub, pausing for the quota window whenever Gmail cuts us off."""
    detector = JobDetector()
    total = len(stubs)
    new_count = 0
    index = 0
    for pause in range(_MAX_QUOTA_WAITS + 1):
        stored, index = _process_batch(stubs, index, client, repo, detector)
        new_count += stored
        if index >= total:
            log.info("Fetched %d new emails (%d already known)", new_count, total - new_count)
            return FetchResult(new_count, False, processed=total, total=total)
        if pause < _MAX_QUOTA_WAITS:
            _pause_for_quota(index, total, pause, sleep, on_quota_wait)
    log.warning(
        "Gmail quota still exhausted at %d/%d messages after %d pauses; "
        "remaining messages deferred to the next sync",
        index, total, _MAX_QUOTA_WAITS,
    )
    return FetchResult(new_count, True, processed=index, total=total)


def _pause_for_quota(
    index: int,
    total: int,
    pause: int,
    sleep: Callable[[float], None],
    on_quota_wait: Callable[[int, int], None] | None,
) -> None:
    """Wait out one quota window, reporting progress so the pause does not look like a hang."""
    log.warning(
        "Gmail quota exhausted at %d/%d messages; waiting %.0fs (pause %d/%d)",
        index, total, _QUOTA_WINDOW_SECONDS, pause + 1, _MAX_QUOTA_WAITS,
    )
    if on_quota_wait is not None:
        on_quota_wait(index, total)
    sleep(_QUOTA_WINDOW_SECONDS)


def _process_batch(
    stubs: list[dict], start: int, client: GmailClient, repo: Repository, detector: JobDetector,
) -> tuple[int, int]:
    """Process stubs from `start`. Returns (newly stored, index reached).

    Stops at the first quota error so the caller can wait and resume from that same message;
    other per-message failures are skipped so one bad email cannot abort the batch.
    """
    new_count = 0
    index = start
    while index < len(stubs):
        stub = stubs[index]
        try:
            new_count += _process_message(stub["id"], client, repo, detector)
        except GmailQuotaExhaustedError:
            return new_count, index
        except (HttpError, ValueError, KeyError) as error:
            log.warning("Skipping message %s: %s", stub["id"], error)
        index += 1
    return new_count, index


def _process_message(
    msg_id: str, client: GmailClient, repo: Repository, detector: JobDetector,
) -> bool:
    """Fetch, parse, classify, and store one message. Returns True if newly stored."""
    if repo.get_email(msg_id):  # Skip if already in DB
        return False

    raw = client.get_message(msg_id)
    email, signals = parse_message(raw)

    # Parse digest emails into individual jobs (before insert so we have count)
    extracted_jobs = parse_digest(email)

    # Detect if this is a job opportunity or platform noise
    is_job, confidence = detector.is_job_opportunity(
        email.subject, email.sender, email.platform,
        email.body_text, len(extracted_jobs),
    )
    email.is_job_related = is_job
    email.confidence = confidence

    _store_email(repo, email, signals, extracted_jobs, msg_id)
    log.debug("Stored email %s: %s (%d jobs)", msg_id, email.subject, len(extracted_jobs))
    return True


def _store_email(
    repo: Repository,
    email: Email,
    signals: list[ExtractedSignal],
    extracted_jobs: list[ScrapedJob],
    msg_id: str,
) -> None:
    """Persist an email, its extracted signals, and any digest jobs."""
    repo.insert_email(email)
    for signal in signals:
        repo.insert_signal(signal)
    for job in extracted_jobs:
        repo.insert_scraped_job(job)

    # For non-digest emails, extract single job URL for "Open Origin"
    if not extracted_jobs:
        origin_url = extract_single_job_url(email.body_text or "", email.platform)
        if origin_url:
            repo.update_email_origin_url(msg_id, origin_url)
