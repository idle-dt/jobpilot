"""Sync orchestration — fetch emails, classify, parse, score, scrape."""

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests

from jobpilot.config import settings
from jobpilot.scraper.constants import SCRAPABLE_DOMAINS, STRATEGY_REQUESTS_THEN_BROWSER
from jobpilot.scraper.job_page import SCRAPE_EXPIRED, JobPageScraper
from jobpilot.services.classification_service import ClassificationService
from jobpilot.storage.models import ScrapedJob
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

SCRAPE_DELAY_SECONDS = 2


@dataclass
class ScrapeProgress:
    """Thread-safe scrape progress tracker."""

    current: int = 0
    total: int = 0
    step: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, current: int, total: int, step: str) -> None:
        """Update progress atomically."""
        with self._lock:
            self.current = current
            self.total = total
            self.step = step

    def to_dict(self) -> dict:
        """Return progress as a dict for JSON serialization."""
        with self._lock:
            return {"current": self.current, "total": self.total, "step": self.step}

    def reset(self) -> None:
        """Reset progress."""
        with self._lock:
            self.current = 0
            self.total = 0
            self.step = ""


# Global progress instance — shared between sync service and routes
scrape_progress = ScrapeProgress()


@dataclass
class SyncResult:
    """Result of a sync operation."""
    new_emails: int
    arbeitnow_jobs: int


class SyncService:
    """Orchestrates the full sync pipeline."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.classification = ClassificationService(repo)

    def run(self) -> SyncResult:
        """Execute full sync: fetch, classify, parse, score, scrape."""
        from jobpilot.gmail.auth import GmailAuth
        from jobpilot.gmail.client import GmailClient
        from jobpilot.gmail.fetcher import fetch_new_emails

        auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)
        creds = auth.get_credentials()

        sync_days = int(self.repo.get_setting("sync_days", "7"))
        since = datetime.now() - timedelta(days=sync_days)
        client = GmailClient(creds)
        new_emails = fetch_new_emails(client, self.repo, since=since)

        self.classification.classify_unprocessed()
        self.classification.parse_existing_digests()

        arbeitnow_count = 0
        try:
            from jobpilot.scraper.arbeitnow import ArbeitNowClient
            arbeitnow = ArbeitNowClient(self.repo)
            arbeitnow_count = arbeitnow.fetch_and_store()
        except (requests.RequestException, ValueError, sqlite3.OperationalError):
            logger.exception("ArbeitNow fetch failed")

        self.classification.score_pending_jobs()
        self._scrape_job_descriptions()

        return SyncResult(new_emails=new_emails, arbeitnow_jobs=arbeitnow_count)

    def _scrape_job_descriptions(self) -> None:
        """Scrape descriptions for LinkedIn and Glassdoor jobs."""
        from jobpilot.classifier.rules import RuleBasedScorer, load_signal_config

        jobs = self.repo.get_jobs_needing_scrape()
        if not jobs:
            return

        config = load_signal_config(self.repo)
        score_threshold = float(
            self.repo.get_setting("score_threshold", str(settings.score_threshold))
        )
        scraper = JobPageScraper()
        scorer = RuleBasedScorer(config=config, score_threshold=score_threshold)
        browser_scraper = None
        success_count = 0

        logger.info("[Scrape] Scraping %d jobs...", len(jobs))
        scrape_progress.update(0, len(jobs), "starting")

        try:
            for i, job in enumerate(jobs, 1):
                scrape_progress.update(i, len(jobs), job.title[:50])
                logger.info("[Scrape] [%d/%d] %s — %s", i, len(jobs), job.title, job.url[:80])
                description, browser_scraper = self._scrape_single_job(
                    job, scraper, browser_scraper, scorer, config,
                )
                if description:
                    success_count += 1
                time.sleep(SCRAPE_DELAY_SECONDS)
        finally:
            if browser_scraper:
                browser_scraper.close()
            scrape_progress.reset()

        logger.info("[Scrape] Batch complete: %d/%d descriptions fetched", success_count, len(jobs))

    def _scrape_single_job(
        self,
        job: ScrapedJob,
        scraper: JobPageScraper,
        browser_scraper: object | None,
        scorer: object,
        config: dict,
    ) -> tuple[str | None, object | None]:
        """Scrape a single job, falling back to browser if needed."""
        domain = _get_scrapable_domain(job.url)
        if domain is None:
            self.repo.mark_scrape_attempted(job.id)
            return None, browser_scraper

        strategy = SCRAPABLE_DOMAINS[domain]
        description = scraper.scrape(job.url)

        if description is None and strategy == STRATEGY_REQUESTS_THEN_BROWSER:
            logger.info("[Scrape] %s — requests failed, falling back to browser", job.title)
            if browser_scraper is None:
                from jobpilot.scraper.browser import BrowserScraper
                browser_scraper = BrowserScraper()
            description = browser_scraper.scrape(job.url)

        if description == SCRAPE_EXPIRED:
            self.repo.toggle_scraped_job_expired(job.id)
            self.repo.mark_scrape_attempted(job.id)
            return None, browser_scraper

        if description:
            self._save_description(job, description, scorer, config)
            logger.info(
                "[Scrape] %s — description saved (%d chars)", job.title, len(description),
            )
        else:
            logger.info("[Scrape] %s — all methods failed, marking as attempted", job.title)
        self.repo.mark_scrape_attempted(job.id)
        return description, browser_scraper

    def _save_description(
        self, job: ScrapedJob, description: str, scorer: object, config: dict,
    ) -> None:
        """Save scraped description and re-score the job."""
        from jobpilot.classifier.features import extract_matched_keywords

        self.repo.update_scraped_job_description(job.id, description)
        text = f"{job.title} {job.company or ''} {job.location or ''} {description}"
        result = scorer.score(job.title, text)
        signals = extract_matched_keywords(text, config, subject=job.title)
        has_signals = signals["positive"] or signals["negative"]
        signals_json = json.dumps(signals) if has_signals else None
        self.repo.update_scraped_job_scores(
            job.id, result.score, None, result.classification,
            matched_signals=signals_json,
        )


def _get_scrapable_domain(url: str) -> str | None:
    """Return the scrapable domain if URL matches, else None."""
    hostname = urlparse(url).hostname or ""
    for domain in SCRAPABLE_DOMAINS:
        if hostname.endswith(domain):
            return domain
    return None
