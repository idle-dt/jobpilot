"""Building the History page: every label in effect, plus the mail the rules rejected.

The not-job-related view sits here rather than on its own page because it is the only
surface showing which named ingest rule rejected an email, and the Emails tab it used to
live on has been replaced by this one. It is a different pipeline stage from a label, and
the template says so rather than blending the two.
"""

import math

from jobpilot.storage.history_repo import VIEW_PREDICATES
from jobpilot.storage.repository import Repository

PER_PAGE = 50

VIEW_NOT_JOB_RELATED = "not_job_related"
DEFAULT_VIEW = "all"
# Job-label views come from the repository's predicate table, so the two cannot drift.
VALID_VIEWS = frozenset(VIEW_PREDICATES) | {VIEW_NOT_JOB_RELATED}

# Chip label and order for the template. A tuple so the UI order is deliberate rather
# than whatever the set happens to iterate.
VIEW_CHIPS = (
    ("all", "All"),
    ("worth_checking", "Worth Checking"),
    ("skip", "Skip"),
    ("not_a_job", "Not a Job"),
    ("assistant", "Assistant"),
    (VIEW_NOT_JOB_RELATED, "Not Job Related"),
)


class HistoryPage:
    """One rendered page of history: its rows, where it sits, and how big it is."""

    def __init__(self, rows: list[dict], total: int, page: int, pages: int, view: str):
        self.rows = rows
        self.total = total
        self.page = page
        self.pages = pages
        self.view = view


class HistoryService:
    """Assembles the History page for one view and page number."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def build_page(self, view: str = DEFAULT_VIEW, page: int = 1) -> HistoryPage:
        """Return one page of history. Invalid input falls back rather than erroring."""
        if view not in VALID_VIEWS:
            view = DEFAULT_VIEW
        page = max(1, page)
        offset = (page - 1) * PER_PAGE
        if view == VIEW_NOT_JOB_RELATED:
            rows, total = self._rejected_mail(offset)
        else:
            rows = self.repo.history.labeled_jobs(view, PER_PAGE, offset)
            total = self.repo.history.count_labeled_jobs(view)
        pages = max(1, math.ceil(total / PER_PAGE))
        return HistoryPage(rows, total, page, pages, view)

    def _rejected_mail(self, offset: int) -> tuple[list[dict], int]:
        """Return one page of non-job mail, shaped like the job rows the template expects."""
        emails = self.repo.get_emails_not_job_related(limit=PER_PAGE, offset=offset)
        rows = [
            {
                "id": email.id,
                "title": email.subject,
                "company": email.platform,
                "url": email.origin_url,
                "non_job_rule": email.non_job_rule,
                "labeled_at": (
                    email.received_at.isoformat() if email.received_at else None
                ),
            }
            for email in emails
        ]
        return rows, self.repo.count_emails_not_job_related()
