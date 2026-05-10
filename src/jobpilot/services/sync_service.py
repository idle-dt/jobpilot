"""Sync orchestration — fetch emails, classify, parse, score, scrape."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from jobpilot.config import settings
from jobpilot.services.classification_service import ClassificationService
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

SCRAPE_DELAY_SECONDS = 2


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
        except Exception:
            logger.exception("ArbeitNow fetch failed")

        self.classification.score_pending_jobs()
        self._scrape_low_confidence_jobs()

        return SyncResult(new_emails=new_emails, arbeitnow_jobs=arbeitnow_count)

    def _scrape_low_confidence_jobs(self) -> None:
        """Scrape full descriptions for jobs with low scoring confidence."""
        from jobpilot.classifier.rules import RuleBasedScorer, load_signal_config
        from jobpilot.scraper.job_page import JobPageScraper

        scrape_threshold = float(
            self.repo.get_setting(
                "scrape_confidence_threshold",
                str(settings.scrape_confidence_threshold),
            )
        )
        score_threshold = float(
            self.repo.get_setting("score_threshold", str(settings.score_threshold))
        )
        jobs = self.repo.get_jobs_needing_scrape(score_threshold, scrape_threshold)
        if not jobs:
            return

        config = load_signal_config(self.repo)
        scraper = JobPageScraper()
        scorer = RuleBasedScorer(config=config, score_threshold=score_threshold)
        logger.info("Scraping %d low-confidence jobs", len(jobs))

        for job in jobs:
            description = scraper.scrape(job.url)
            if description:
                self.repo.update_scraped_job_description(job.id, description)
                text = f"{job.title} {job.company or ''} {job.location or ''} {description}"
                result = scorer.score(job.title, text)
                self.repo.update_scraped_job_scores(
                    job.id, result.score, None, result.classification,
                )
            self.repo.mark_scrape_attempted(job.id)
            time.sleep(SCRAPE_DELAY_SECONDS)
