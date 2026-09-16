"""Cancelling a label, and deciding what that should take with it.

One place owns the question, because a cancel touches three things that must agree: the
label on the job, the application it created in the Tracker, and the record barring a run
from reaching that verdict again.

The order below is the important part. The Tracker is asked *before* anything is written,
so a refusal leaves the job exactly as it was rather than clearing the label and stranding
an application behind it.
"""

import logging

from jobpilot.services.tracker_service import TrackerService
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

REFUSAL_NOT_LABELED = "the job carries no label to cancel"
REFUSAL_UNKNOWN_JOB = "no such job"


class CancelResult:
    """What a cancel did, or why it did nothing.

    ``cancelled`` is the only success signal. A refusal means *nothing* was written —
    not the label, not the Tracker, not the rejection record.
    """

    def __init__(
        self, cancelled: bool, refusal: str | None = None, untracked: bool = False,
    ):
        self.cancelled = cancelled
        self.refusal = refusal
        self.untracked = untracked


class CancelService:
    """Removes a label, the Tracker entry it created, and optionally records the verdict."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def cancel(self, job_id: int, record_rejection: bool) -> CancelResult:
        """Clear a job's label. Returns what happened.

        ``record_rejection`` separates a deliberate cancel from an immediate undo. A
        cancel says the verdict was wrong and is recorded, so no future run may reach it
        again. An undo says the click was a mistake and records nothing, leaving a run
        free to decide the job on its merits later.
        """
        job = self.repo.get_scraped_job(job_id)
        if not job:
            return CancelResult(False, REFUSAL_UNKNOWN_JOB)
        if not job.user_label:
            return CancelResult(False, REFUSAL_NOT_LABELED)

        untracked, refusal = TrackerService(self.repo).untrack_scraped_job(job_id)
        if refusal:
            return CancelResult(False, refusal)

        if record_rejection:
            self.repo.labels.rejections.record(
                job_id, job.user_label, job.label_source, job.label_reason,
            )
        self.repo.update_scraped_job_label(job_id, None)
        logger.info(
            "Cancelled '%s' on scraped job %d (rejection recorded: %s)",
            job.user_label, job_id, record_rejection,
        )
        return CancelResult(True, untracked=untracked)
