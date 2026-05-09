"""ArbeitNow API client for fetching remote jobs."""

import html
import logging
import re
from datetime import datetime
from urllib.parse import urlparse

import requests

from jobpilot.storage.models import ScrapedJob
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

API_URL = "https://www.arbeitnow.com/api/job-board-api"
RATE_LIMIT_SECONDS = 3600  # 1 hour
REQUEST_TIMEOUT = 15
MAX_PAGES = 5


class ArbeitNowClient:
    """Fetches and filters jobs from ArbeitNow's free public API."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def should_fetch(self) -> bool:
        """Check if ArbeitNow fetching is enabled and rate limit allows it."""
        enabled = self.repo.get_setting("arbeitnow_enabled", "false")
        if enabled != "true":
            return False
        last = self.repo.get_setting("arbeitnow_last_fetch")
        if not last:
            return True
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
            return elapsed >= RATE_LIMIT_SECONDS
        except ValueError:
            return True

    def fetch_and_store(self) -> int:
        """Fetch jobs from ArbeitNow API, filter, and store. Returns count of new jobs."""
        if not self.should_fetch():
            return 0

        visa_only = self.repo.get_setting("arbeitnow_visa_only", "false") == "true"

        # Load primary tech keywords for client-side filtering
        tech_prefs = self.repo.get_preferences("tech_keyword_primary")
        filter_keywords = [p.value.lower() for p in tech_prefs] if tech_prefs else []

        new_count = 0
        page = 1

        try:
            while page <= MAX_PAGES:
                params = {"page": page}
                resp = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                jobs = data.get("data", [])
                if not jobs:
                    break

                for job_data in jobs:
                    # Skip non-remote jobs
                    if not job_data.get("remote"):
                        continue

                    # Visa sponsorship filter
                    if visa_only and not job_data.get("visa_sponsorship"):
                        continue

                    title = _strip_html(job_data.get("title", ""))
                    description = _strip_html(job_data.get("description", ""))
                    tags = " ".join(t.lower() for t in job_data.get("tags", []))

                    # Client-side keyword filter
                    if filter_keywords:
                        searchable = f"{title} {description} {tags}".lower()
                        if not any(kw in searchable for kw in filter_keywords):
                            continue

                    url = job_data.get("url", "")
                    if not url or not _is_safe_url(url):
                        continue

                    job = ScrapedJob(
                        id=None,
                        source="arbeitnow",
                        title=title,
                        company=job_data.get("company_name"),
                        location=job_data.get("location"),
                        url=url,
                        remote=True,
                        description=description,
                    )
                    if self.repo.insert_scraped_job(job):
                        new_count += 1

                # Check for next page
                links = data.get("links", {})
                if not links.get("next"):
                    break
                page += 1

            self.repo.set_setting("arbeitnow_last_fetch", datetime.now().isoformat())
            logger.info("ArbeitNow: fetched %d new jobs from %d pages", new_count, page)
        except requests.RequestException:
            logger.exception("ArbeitNow API fetch failed")

        return new_count


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _is_safe_url(url: str) -> bool:
    """Validate URL has safe scheme and host."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False
