"""Sync orchestration — fetch emails, classify, parse, score, scrape."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import requests

from jobpilot.config import settings
from jobpilot.scraper.constants import SCRAPABLE_DOMAINS, STRATEGY_REQUESTS_THEN_BROWSER
from jobpilot.scraper.job_page import SCRAPE_EXPIRED, JobPageScraper
from jobpilot.services.classification_service import ClassificationService
from jobpilot.services.sync_state import sync_state
from jobpilot.storage.models import ScrapedJob
from jobpilot.storage.repository import Repository

if TYPE_CHECKING:
    from jobpilot.classifier.rules import RuleBasedScorer, SignalConfig
    from jobpilot.scraper.browser import BrowserScraper

logger = logging.getLogger(__name__)

SCRAPE_DELAY_SECONDS = 2
_TITLE_DISPLAY_LEN = 60
_TITLE_LOG_LEN = 80


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
        new_emails = self._fetch_emails()

        sync_state.update("classifying", "Classifying emails…")
        self.classification.classify_unprocessed()
        logger.info("[Sync] Classification complete")

        sync_state.update("parsing", "Parsing digests…")
        self.classification.parse_existing_digests()
        logger.info("[Sync] Digest parsing complete")

        arbeitnow_count = self._fetch_arbeitnow()

        sync_state.update("scoring", "Scoring scraped jobs…")
        self.classification.score_pending_jobs()
        logger.info("[Sync] Scoring complete")

        self._scrape_job_descriptions()

        self.repo.set_setting("last_sync_time", datetime.now().isoformat())

        logger.info(
            "[Sync] Pipeline complete: %d emails, %d arbeitnow jobs",
            new_emails, arbeitnow_count,
        )
        return SyncResult(new_emails=new_emails, arbeitnow_jobs=arbeitnow_count)

    def _fetch_emails(self) -> int:
        """Fetch new emails from Gmail."""
        from jobpilot.gmail.auth import GmailAuth
        from jobpilot.gmail.client import GmailClient
        from jobpilot.gmail.fetcher import fetch_new_emails

        sync_state.update("fetching", "Fetching emails from Gmail…")
        auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)
        creds = auth.get_credentials()
        sync_days = int(self.repo.get_setting("sync_days", "7"))
        since = datetime.now() - timedelta(days=sync_days)
        client = GmailClient(creds)
        new_emails = fetch_new_emails(client, self.repo, since=since)
        logger.info("[Sync] Fetched %d new emails", new_emails)
        return new_emails

    def _fetch_arbeitnow(self) -> int:
        """Fetch jobs from ArbeitNow API."""
        try:
            sync_state.update("fetching_arbeitnow", "Fetching ArbeitNow jobs…")
            from jobpilot.scraper.arbeitnow import ArbeitNowClient
            arbeitnow = ArbeitNowClient(self.repo)
            count = arbeitnow.fetch_and_store()
            logger.info("[Sync] ArbeitNow: fetched %d jobs", count)
            return count
        except (requests.RequestException, ValueError, sqlite3.OperationalError):
            logger.exception("[Sync] ArbeitNow fetch failed")
            return 0

    def _scrape_job_descriptions(self) -> None:
        """Scrape descriptions for LinkedIn and Glassdoor jobs."""
        from jobpilot.classifier.rules import load_signal_config

        jobs = self.repo.get_jobs_needing_scrape()
        if not jobs:
            return

        config = load_signal_config(self.repo)
        scraper = JobPageScraper()
        scorer = self._build_scorer(config)
        success = self._run_scrape_batch(jobs, scraper, scorer, config)
        logger.info("[Sync] Scraping complete: %d/%d descriptions fetched", success, len(jobs))

    def _build_scorer(self, config: SignalConfig) -> RuleBasedScorer:
        """Create a RuleBasedScorer with the current score threshold."""
        from jobpilot.classifier.rules import RuleBasedScorer

        score_threshold = float(
            self.repo.get_setting("score_threshold", str(settings.score_threshold))
        )
        return RuleBasedScorer(config=config, score_threshold=score_threshold)

    def _run_scrape_batch(
        self, jobs: list[ScrapedJob], scraper: JobPageScraper,
        scorer: RuleBasedScorer, config: SignalConfig,
    ) -> int:
        """Run scrape loop over jobs. Returns success count."""
        browser_scraper: BrowserScraper | None = None
        success_count = 0
        logger.info("[Sync] Scraping %d jobs…", len(jobs))
        sync_state.update("scraping", "Starting scrape…", 0, len(jobs))

        try:
            for i, job in enumerate(jobs, 1):
                sync_state.update("scraping", job.title[:_TITLE_DISPLAY_LEN], i, len(jobs))
                logger.info(
                    "[Sync] [Scrape %d/%d] %s — %s",
                    i, len(jobs), job.title[:_TITLE_LOG_LEN], job.url[:_TITLE_LOG_LEN],
                )
                desc, browser_scraper = self._scrape_single_job(
                    job, scraper, browser_scraper, scorer, config,
                )
                if desc:
                    success_count += 1
                time.sleep(SCRAPE_DELAY_SECONDS)
        finally:
            if browser_scraper:
                browser_scraper.close()
        return success_count

    def _scrape_single_job(
        self,
        job: ScrapedJob,
        scraper: JobPageScraper,
        browser_scraper: BrowserScraper | None,
        scorer: RuleBasedScorer,
        config: SignalConfig,
    ) -> tuple[str | None, BrowserScraper | None]:
        """Scrape a single job, falling back to browser if needed."""
        domain = _get_scrapable_domain(job.url)
        if domain is None:
            logger.warning("[Sync] %s — unsupported domain, skipping: %s", job.title, job.url)
            self.repo.mark_scrape_attempted(job.id)
            return None, browser_scraper

        strategy = SCRAPABLE_DOMAINS[domain]
        description = scraper.scrape(job.url)

        if description is None and strategy == STRATEGY_REQUESTS_THEN_BROWSER:
            logger.info("[Sync] %s — requests failed, falling back to browser", job.title)
            if browser_scraper is None:
                from jobpilot.scraper.browser import BrowserScraper
                browser_scraper = BrowserScraper()
            description = browser_scraper.scrape(job.url)

        # SCRAPE_EXPIRED is a non-None string, so the browser fallback above
        # (which checks `description is None`) is skipped when requests detects expiry.
        if description == SCRAPE_EXPIRED:
            self.repo.toggle_scraped_job_expired(job.id)
            self.repo.mark_scrape_attempted(job.id)
            return None, browser_scraper

        if description:
            self._save_description(job, description, scorer, config)
            logger.info(
                "[Sync] %s — description saved (%d chars)", job.title, len(description),
            )
        else:
            logger.info("[Sync] %s — all methods failed, marking as attempted", job.title)
        self.repo.mark_scrape_attempted(job.id)
        return description, browser_scraper

    def _save_description(
        self, job: ScrapedJob, description: str, scorer: RuleBasedScorer, config: SignalConfig,
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
        if hostname == domain or hostname.endswith(f".{domain}"):
            return domain
    return None
