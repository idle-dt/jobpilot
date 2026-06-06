"""Business logic for the inbox review queue."""

import logging

from jobpilot.storage.models import ExtractedSignal
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

# Max items of each type pulled into the review queue.
INBOX_REVIEW_LIMIT = 50
# Below this active-noise-model probability an item is flagged as likely not-a-job.
NOISE_CONFIDENCE_THRESHOLD = 0.3

# Display ordering for extracted signals (tech_stack first, platform last).
SIGNAL_PRIORITY = {
    "tech_stack": 0,
    "location": 1,
    "salary": 2,
    "job_title": 3,
    "seniority": 4,
    "negative": 5,
    "platform": 6,
}
_UNKNOWN_SIGNAL_RANK = 99

# Allowed sort modes for the review queue and the default when one is invalid.
VALID_SORTS = frozenset({"score_desc", "score_asc", "date_desc", "date_asc"})
DEFAULT_SORT = "score_desc"


def sort_signals(signals: list[ExtractedSignal]) -> list[ExtractedSignal]:
    """Sort signals by display priority (tech_stack first, platform last)."""
    return sorted(
        signals, key=lambda s: SIGNAL_PRIORITY.get(s.signal_type, _UNKNOWN_SIGNAL_RANK)
    )


class InboxService:
    """Builds the review queue of emails and scraped jobs needing feedback."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def build_review_queue(self, sort: str = DEFAULT_SORT) -> list[dict]:
        """Return merged, sorted review items with signals, predictions, descriptions."""
        if sort not in VALID_SORTS:
            sort = DEFAULT_SORT
        emails = self.repo.get_emails_for_review(limit=INBOX_REVIEW_LIMIT)
        scraped = self.repo.get_scraped_jobs_for_review(limit=INBOX_REVIEW_LIMIT)
        for email in emails:
            email.signals = sort_signals(self.repo.get_signals_for_email(email.id))
        items = self._merge_items(emails, scraped)
        self._sort_items(items, sort)
        self._attach_predictions(items)
        return items

    @staticmethod
    def _merge_items(emails: list, scraped: list) -> list[dict]:
        """Combine emails and scraped jobs into a uniform sortable item list."""
        items: list[dict] = []
        for email in emails:
            items.append({
                "type": "email",
                "obj": email,
                "score": email.raw_score or 0,
                "date": email.received_at.isoformat() if email.received_at else "",
            })
        for job in scraped:
            items.append({
                "type": "scraped",
                "obj": job,
                "score": job.score or 0,
                "date": job.scraped_at or job.posted_date or "",
            })
        return items

    @staticmethod
    def _sort_items(items: list[dict], sort: str) -> None:
        """Sort items in place by score or date, ascending or descending."""
        reverse = sort.endswith("_desc")
        key = "score" if sort.startswith("score") else "date"
        items.sort(key=lambda x: x[key], reverse=reverse)

    def _attach_predictions(self, items: list[dict]) -> None:
        """Attach ML predictions, descriptions, and noise flags to each item."""
        email_ids = [i["obj"].id for i in items if i["type"] == "email"]
        job_ids = [str(i["obj"].id) for i in items if i["type"] == "scraped"]
        email_preds = (
            self.repo.get_predictions_for_items("email", email_ids) if email_ids else {}
        )
        job_preds = (
            self.repo.get_predictions_for_items("scraped_job", job_ids) if job_ids else {}
        )
        desc_map = self.repo.get_descriptions_for_emails(email_ids) if email_ids else {}
        for item in items:
            if item["type"] == "email":
                desc, signals = desc_map.get(item["obj"].id, (None, None))
                item["description"] = desc
                item["matched_signals"] = signals
                item["predictions"] = email_preds.get(item["obj"].id, [])
            else:
                item["predictions"] = job_preds.get(str(item["obj"].id), [])
            item["noise_flag"] = self._is_noise_flagged(item["predictions"])

    @staticmethod
    def _is_noise_flagged(predictions: list[dict]) -> bool:
        """Return True if the active noise model confidently marks the item not-a-job."""
        return any(
            p.get("model_type") == "noise"
            and p.get("is_active")
            and p.get("prediction") == "not_a_job"
            and (p.get("probability") or 1) < NOISE_CONFIDENCE_THRESHOLD
            for p in predictions
        )

    def count_review_totals(self) -> tuple[int, int, int]:
        """Return (review_total, worth_checking_count, skip_count) for the queue."""
        review_total = (
            self.repo.count_emails_for_review()
            + self.repo.count_scraped_jobs_for_review()
        )
        worth_checking_count = (
            self.repo.count_emails_for_review("worth_checking")
            + self.repo.count_scraped_jobs_for_review("worth_checking")
        )
        skip_count = review_total - worth_checking_count
        return review_total, worth_checking_count, skip_count
