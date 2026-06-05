"""Business logic for the application tracker."""

import logging
import re
from datetime import datetime

from jobpilot.storage.models import Application
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

# Canonical set of valid application statuses. Also mirrored in the SQL CHECK
# constraints in storage/database.py. Adding a status here means adding it to
# STATUS_SORT_RANK below and both CHECK lists; the test_status_* parity guards in
# tests/test_storage.py fail the build if any copy drifts.
APPLICATION_STATUSES = (
    "saved", "applied", "screening", "technical",
    "onsite", "offer", "accepted", "rejected",
    "withdrawn", "no_response", "expired",
)

STATUS_LABELS = {s: s.replace("_", " ").title() for s in APPLICATION_STATUSES}
STATUS_LABELS["no_response"] = "No Response"

# Pipeline-stage ordering for the tracker list: active stages first (furthest
# along at top), then terminal states. Lower rank sorts first. Must cover every
# status in APPLICATION_STATUSES (guarded by test_status_sort_rank_covers_all_statuses)
# — an uncovered status silently falls to _UNKNOWN_STATUS_RANK at the bottom.
STATUS_SORT_RANK: dict[str, int] = {
    "offer": 0,
    "onsite": 1,
    "technical": 2,
    "screening": 3,
    "applied": 4,
    "saved": 5,
    "accepted": 6,
    "expired": 7,
    "rejected": 8,
    "no_response": 9,
    "withdrawn": 10,
}
# Fallback rank for any unknown status — sorts after all known statuses.
_UNKNOWN_STATUS_RANK = 99

_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

# Fields the PATCH endpoint is allowed to modify.
# "status" is deliberately excluded — status changes must go through
# update_status() so that history is recorded.
PATCH_BLOCKED_FIELDS = frozenset({"id", "status", "email_id", "created_at", "updated_at"})


def validate_url(url: str) -> str | None:
    """Return the URL if it has a safe scheme, else None."""
    if not url:
        return None
    return url if _URL_SCHEME_RE.match(url) else None


class TrackerService:
    """Application tracker business logic."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def list_applications(
        self, status_filter: str = "",
    ) -> tuple[list[Application], dict[str, int], int]:
        """Return (apps, counts_by_status, total)."""
        if status_filter and status_filter not in APPLICATION_STATUSES:
            status_filter = ""
        apps = self.repo.get_applications_by_status(
            status=status_filter or None,
        )
        apps.sort(key=self._sort_key)
        counts = self.repo.count_applications_by_status()
        total = sum(counts.values())
        return apps, counts, total

    @staticmethod
    def _sort_key(app: Application) -> tuple[int, float]:
        """Sort by pipeline stage, then most-recently-changed first within a stage."""
        rank = STATUS_SORT_RANK.get(app.status, _UNKNOWN_STATUS_RANK)
        recency = 0.0
        if app.last_status_change:
            try:
                recency = datetime.fromisoformat(app.last_status_change).timestamp()
            except ValueError:  # malformed timestamp — keep default, never crash the list
                pass
        return rank, -recency

    def get_application(self, app_id: int) -> Application | None:
        """Get a single application."""
        return self.repo.get_application(app_id)

    def get_history(self, app_id: int) -> list:
        """Get status history for an application."""
        return self.repo.get_application_history(app_id)

    def create_application(
        self, *, company: str, role_title: str, status: str = "applied",
        location: str | None = None, salary_range: str | None = None,
        job_url: str | None = None, platform: str | None = None,
        contact_name: str | None = None, contact_email: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Create a new tracked application. Returns new ID."""
        if status not in APPLICATION_STATUSES:
            status = "applied"
        app = Application(
            id=None, company=company, role_title=role_title,
            status=status, location=location, salary_range=salary_range,
            job_url=validate_url(job_url) if job_url else None,
            platform=platform, contact_name=contact_name,
            contact_email=contact_email, notes=notes,
        )
        return self.repo.insert_application(app)

    def update_fields(self, app_id: int, fields: dict[str, str | None]) -> bool:
        """Partial update, rejecting blocked fields. Returns True if updated."""
        safe = {k: v for k, v in fields.items() if k not in PATCH_BLOCKED_FIELDS}
        if not safe:
            return False
        if "job_url" in safe:
            raw = str(safe["job_url"]).strip() if safe["job_url"] else None
            safe["job_url"] = validate_url(raw) if raw else None
        return self.repo.update_application(app_id, **safe)

    def update_status(self, app_id: int, new_status: str) -> bool:
        """Update status with history recording. Returns False on bad status."""
        if new_status not in APPLICATION_STATUSES:
            return False
        self.repo.update_application_status(app_id, new_status)
        return True

    def delete_application(self, app_id: int) -> None:
        """Delete an application and its history."""
        self.repo.delete_application(app_id)

    def auto_track_scraped_job(self, job_id: int) -> None:
        """Auto-create a tracker entry from a scraped job if not already tracked."""
        existing = self.repo.get_application_by_scraped_job_id(job_id)
        if existing:
            return
        job = self.repo.get_scraped_job(job_id)
        if not job or job.expired:
            return
        app = Application(
            id=None,
            company=job.company or "Unknown",
            role_title=job.title,
            status="saved",
            scraped_job_id=job.id,
            location=job.location,
            remote=job.remote,
            salary_range=job.salary,
            job_url=job.url if job.url.startswith(("http://", "https://")) else None,
            platform=job.source,
        )
        self.repo.insert_application(app)
        logger.info("Auto-tracked scraped job %d as application", job_id)
