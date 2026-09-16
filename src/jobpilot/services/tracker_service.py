"""Business logic for the application tracker."""

import logging
import re
from datetime import datetime

from jobpilot.storage.models import Application, ScrapedJob
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

# An automatic untrack deletes the whole application row, so it must only ever fire on a
# row nobody has touched. The two tuples below partition every column a user can PATCH
# (ApplicationRepository._UPDATABLE_COLUMNS): fields auto-tracking fills from the scraped
# job, and fields it never writes at all. test_untrack_guard_covers_every_editable_column
# fails the build if a new editable column is added to neither.
AUTO_TRACKED_FIELDS = (
    "company", "role_title", "location", "remote", "salary_range", "job_url", "platform",
)
USER_AUTHORED_FIELDS = (
    "notes", "contact_name", "contact_email", "offer_salary", "offer_currency",
    "offer_equity", "offer_relocation_package", "offer_notes",
)
UNTRACKED_STATUS = "saved"
UNKNOWN_COMPANY = "Unknown"

REFUSAL_ADVANCED = "the application has moved beyond Saved"
REFUSAL_HAS_HISTORY = "the application has a status history"
REFUSAL_HAS_USER_DATA = "the application carries notes or details you entered"
REFUSAL_EDITED = "you have edited the application's details"

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

# Default sort (no param): pipeline rank, matching the historical behavior.
# Only the Applied date is user-sortable; every other column keeps pipeline order.
DEFAULT_TRACKER_SORT = "status"

_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


def _parse_tracker_sort(raw: str) -> tuple[str, str]:
    """Parse the sort param into (column, direction). Returns default on bad input."""
    if raw == "applied_asc":
        return "applied", "asc"
    if raw == "applied_desc":
        return "applied", "desc"
    return "status", "asc"


def canonical_tracker_sort(raw: str) -> str:
    """Normalize an untrusted sort param to a known-good value for safe reflection."""
    column, direction = _parse_tracker_sort(raw)
    return DEFAULT_TRACKER_SORT if column == "status" else f"applied_{direction}"


def _iso_to_timestamp(value: str | None) -> float:
    """Parse an ISO timestamp to epoch seconds; 0.0 on missing/malformed input."""
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:  # malformed timestamp — never crash the list
        return 0.0


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
        self, status_filter: str = "", sort: str = DEFAULT_TRACKER_SORT,
    ) -> tuple[list[Application], dict[str, int], int]:
        """Return (apps, counts_by_status, total), sorted per the sort param."""
        if status_filter and status_filter not in APPLICATION_STATUSES:
            status_filter = ""
        apps = self.repo.get_applications_by_status(
            status=status_filter or None,
        )
        apps = self._sort_applications(apps, sort)
        counts = self.repo.count_applications_by_status()
        total = sum(counts.values())
        return apps, counts, total

    def _sort_applications(
        self, apps: list[Application], sort: str,
    ) -> list[Application]:
        """Sort by applied date when requested, else pipeline rank.

        Rows with no applied_at always sort last, in both directions.
        """
        column, direction = _parse_tracker_sort(sort)
        if column == "status":
            apps.sort(key=self._sort_key)
            return apps
        present = [a for a in apps if a.applied_at]
        missing = [a for a in apps if not a.applied_at]
        # Secondary sort first; a stable primary sort then preserves it within ties.
        present.sort(key=self._sort_key)
        present.sort(key=lambda a: _iso_to_timestamp(a.applied_at),
                     reverse=(direction == "desc"))
        missing.sort(key=self._sort_key)
        return present + missing

    @staticmethod
    def _sort_key(app: Application) -> tuple[int, float]:
        """Sort by pipeline stage, then most-recently-changed first within a stage."""
        rank = STATUS_SORT_RANK.get(app.status, _UNKNOWN_STATUS_RANK)
        return rank, -_iso_to_timestamp(app.last_status_change)

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

    def untrack_scraped_job(self, job_id: int) -> tuple[bool, str | None]:
        """Delete the application auto-created for a job. Returns (deleted, refusal).

        Only an untouched entry is deleted: one still at 'saved', with no status history
        and nothing the user typed. Anything else is refused, because an automatic
        untrack must never destroy work the user did by hand.

        ``(False, None)`` means there was nothing to untrack, which is not a refusal.
        """
        app = self.repo.get_application_by_scraped_job_id(job_id)
        if not app:
            return False, None
        refusal = self._untrack_refusal(app)
        if refusal:
            return False, refusal
        self.repo.delete_application(app.id)
        logger.info("Untracked application %d for scraped job %d", app.id, job_id)
        return True, None

    def _untrack_refusal(self, app: Application) -> str | None:
        """Return why this application must not be auto-deleted, or None if it may be."""
        if app.status != UNTRACKED_STATUS:
            return REFUSAL_ADVANCED
        if self.repo.get_application_history(app.id):
            return REFUSAL_HAS_HISTORY
        if any(getattr(app, name, None) for name in USER_AUTHORED_FIELDS):
            return REFUSAL_HAS_USER_DATA
        if self._differs_from_source(app):
            return REFUSAL_EDITED
        return None

    def _differs_from_source(self, app: Application) -> bool:
        """True if any auto-filled field no longer matches what auto-tracking would write.

        Checked by comparison rather than against a list of "user fields", because the
        user can PATCH the auto-filled columns too — correcting a company that came
        through as 'Unknown', say. Comparing catches that without a second allowlist to
        drift out of step with the PATCH endpoint.

        A re-scrape that changed the job's own details also trips this, which refuses a
        cancel that would have been safe. That is the harmless direction.
        """
        job = self.repo.get_scraped_job(app.scraped_job_id) if app.scraped_job_id else None
        if not job:
            return True
        expected = self._auto_tracked_values(job)
        return any(getattr(app, name, None) != expected[name] for name in AUTO_TRACKED_FIELDS)

    @staticmethod
    def _auto_tracked_values(job: ScrapedJob) -> dict:
        """The application fields auto-tracking derives from a scraped job.

        One source of truth for both writing the row and later recognising an untouched
        one; if these drifted apart, every auto-tracked row would look edited.
        """
        return {
            "company": job.company or UNKNOWN_COMPANY,
            "role_title": job.title,
            "location": job.location,
            "remote": job.remote,
            "salary_range": job.salary,
            "job_url": job.url if job.url.startswith(("http://", "https://")) else None,
            "platform": job.source,
        }

    def auto_track_scraped_job(self, job_id: int) -> bool:
        """Auto-create a tracker entry from a scraped job. Returns True if one was made.

        Idempotent: an already-tracked job, a missing job, or an expired one returns
        False without writing. Callers use the return value to report how many entries a
        bulk run actually added.
        """
        existing = self.repo.get_application_by_scraped_job_id(job_id)
        if existing:
            return False
        job = self.repo.get_scraped_job(job_id)
        if not job or job.expired:
            return False
        app = Application(
            id=None, status=UNTRACKED_STATUS, scraped_job_id=job.id,
            **self._auto_tracked_values(job),
        )
        self.repo.insert_application(app)
        logger.info("Auto-tracked scraped job %d as application", job_id)
        return True
