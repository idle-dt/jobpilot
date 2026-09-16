"""Bulk label writes and source-scoped reverts for scraped jobs.

Kept out of job_repo.py, which is already over the 300-line limit. The single
source of truth for who authored a label is ``scraped_jobs.label_source``:
``'user'`` for a click in the UI, ``'assistant'`` for a ``label-batch`` run, and
NULL while the job is unlabeled. It says nothing about correctness, and it is
unrelated to ``ml_predictions`` — an assistant label is not a model prediction.
"""

import sqlite3
from dataclasses import dataclass, field

from jobpilot.storage.rejection_repo import RejectionRepository

LABEL_VOCABULARY = ("worth_checking", "skip", "not_a_job")
ASSISTANT_SOURCE = "assistant"
USER_SOURCE = "user"

# A hand-back, deliberately outside LABEL_VOCABULARY. It says the run was under the
# confidence floor on this job, not that the job is bad. Never written to user_label,
# never counted as a label, never training data.
PASSED = "passed"

# Rejection reasons. A rejection writes nothing: the job stays in the queue
# exactly as it was, which is not the same as labeling it 'skip'.
REASON_UNKNOWN_JOB = "unknown job"
REASON_INVALID_LABEL = "invalid label"
REASON_ALREADY_LABELED = "already labeled"
REASON_ALREADY_PASSED = "already passed"
# The user cancelled this exact label on this job. Refusing it here rather than in the
# prompt means an agent that ignores its instructions still cannot re-apply it.
REASON_PREVIOUSLY_REJECTED = "previously rejected by user"
# An entry with no stated reason is an omission with extra steps.
REASON_MISSING_REASON = "entry without a reason"

# SQLite's default parameter limit is 999; chunk IN clauses well below it.
_ID_CHUNK_SIZE = 500

# Writing a label clears any hand-back with it: the job is decided, so "a run passed on
# this" is no longer true, and leaving the flag would inflate passed_job_ids().
_APPLY_LABEL_SQL = (
    "UPDATE scraped_jobs SET user_label = ?, label_source = ?, label_reason = ?,"
    " labeled_at = datetime('now'), ai_passed_at = NULL, ai_passed_reason = NULL"
    " WHERE id = ?"
)
_CLEAR_BY_SOURCE_SQL = (
    "UPDATE scraped_jobs SET user_label = NULL, labeled_at = NULL,"
    " label_source = NULL, label_reason = NULL WHERE label_source = ?"
)
_APPLY_PASS_SQL = (
    "UPDATE scraped_jobs SET ai_passed_at = datetime('now'),"
    " ai_passed_reason = ? WHERE id = ?"
)
_CLEAR_PASSED_SQL = (
    "UPDATE scraped_jobs SET ai_passed_at = NULL, ai_passed_reason = NULL"
    " WHERE ai_passed_at IS NOT NULL"
)
# The predicate defining a run's input, and so also the coverage denominator: unlabeled,
# not already handed back, and not auto-skipped by the scorer.
_EXPORTABLE_WHERE = (
    "user_label IS NULL AND ai_passed_at IS NULL AND classification != 'skip'"
)


@dataclass(frozen=True)
class LabelEntry:
    """One requested label from a bulk run.

    ``confidence`` is the caller's stated confidence, not a model probability;
    the CLI enforces the floor before entries reach this repository.
    """

    job_id: int
    label: str
    confidence: float | None = None
    reason: str | None = None
    """Why this label was chosen. Stored on the row and shown in the UI."""


@dataclass(frozen=True)
class JobState:
    """What the repository must know about a job before writing a verdict to it.

    ``rejected`` holds the labels the user has cancelled on this job. A bulk run may
    never re-apply one of them; a user click may, because changing your mind is allowed.
    """

    user_label: str | None
    ai_passed_at: str | None
    rejected: frozenset[str]


@dataclass(frozen=True)
class LabelRejection:
    """An entry that was not written, and why."""

    reason: str
    job_id: int | None = None
    label: str | None = None


@dataclass
class BatchResult:
    """Outcome of one bulk apply: what was written and what was refused."""

    applied: list[LabelEntry] = field(default_factory=list)
    rejected: list[LabelRejection] = field(default_factory=list)


class LabelRepository:
    """Bulk label writes and source-scoped reverts for scraped jobs."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.rejections = RejectionRepository(conn)

    def apply_labels(
        self,
        entries: list[LabelEntry],
        force: bool = False,
        dry_run: bool = False,
    ) -> BatchResult:
        """Apply validated labels in one transaction. Returns applied and rejected rows.

        An entry is rejected — leaving the row untouched — when its label is
        outside ``LABEL_VOCABULARY``, its job id does not exist, or the job already
        carries a label and ``force`` is not set. One bad entry never aborts the
        run. With ``dry_run`` the same decisions are made and nothing is written.
        """
        result = BatchResult()
        existing = self.job_states([e.job_id for e in entries])
        writes: list[tuple[str, str, str | None, int]] = []
        for entry in entries:
            reason = self._rejection_reason(entry, existing, force)
            if reason:
                result.rejected.append(LabelRejection(reason, entry.job_id, entry.label))
                continue
            writes.append((entry.label, ASSISTANT_SOURCE, entry.reason, entry.job_id))
            result.applied.append(entry)
        if writes and not dry_run:
            self.conn.executemany(_APPLY_LABEL_SQL, writes)
            self.conn.commit()
        return result

    def mark_passed(
        self, entries: list[LabelEntry], dry_run: bool = False,
    ) -> BatchResult:
        """Hand jobs back to the user, in one transaction.

        A pass takes the job out of future exports without labeling it and without
        moving it: it stays in the review queue for the user to decide. There is no
        ``force`` — a pass never overrides a judgment.
        """
        result = BatchResult()
        state = self.job_states([e.job_id for e in entries])
        writes: list[tuple[str | None, int]] = []
        for entry in entries:
            refusal = self._pass_refusal(entry, state)
            if refusal:
                result.rejected.append(LabelRejection(refusal, entry.job_id, entry.label))
                continue
            writes.append((entry.reason, entry.job_id))
            result.applied.append(entry)
        if writes and not dry_run:
            self.conn.executemany(_APPLY_PASS_SQL, writes)
            self.conn.commit()
        return result

    def passed_job_ids(self) -> list[int]:
        """Return the ids of every job a run has handed back, in id order."""
        rows = self.conn.execute(
            "SELECT id FROM scraped_jobs WHERE ai_passed_at IS NOT NULL ORDER BY id",
        ).fetchall()
        return [row["id"] for row in rows]

    def clear_passed(self) -> int:
        """Clear every hand-back so the next run reconsiders those jobs."""
        cursor = self.conn.execute(_CLEAR_PASSED_SQL)
        self.conn.commit()
        return cursor.rowcount

    def export_rows(self) -> list[dict]:
        """Return a run's input: every job awaiting a verdict, with its cancelled labels.

        Shaped for an agent rather than for the UI, so a caller needs no SQL and no
        knowledge of which columns define the queue.
        """
        rows = self.conn.execute(
            "SELECT id, title, company, location, url, description"
            f" FROM scraped_jobs WHERE {_EXPORTABLE_WHERE} ORDER BY id",
        ).fetchall()
        ids = [row["id"] for row in rows]
        rejected = self.job_states(ids)
        return [
            dict(row, rejected_labels=sorted(rejected[row["id"]].rejected))
            for row in rows
        ]

    def review_queue_ids(self) -> list[int]:
        """Return the ids a run must account for, in id order.

        This is the coverage denominator: an id here that a run returns as neither a
        label nor a pass was dropped without a trace.
        """
        rows = self.conn.execute(
            f"SELECT id FROM scraped_jobs WHERE {_EXPORTABLE_WHERE} ORDER BY id",
        ).fetchall()
        return [row["id"] for row in rows]

    def clear_labels_by_source(self, source: str) -> int:
        """Clear user_label, labeled_at and label_source for rows from one author."""
        cursor = self.conn.execute(_CLEAR_BY_SOURCE_SQL, (source,))
        self.conn.commit()
        return cursor.rowcount

    def job_ids_by_source(self, source: str) -> list[int]:
        """Return the ids of every job currently labeled by one author."""
        rows = self.conn.execute(
            "SELECT id FROM scraped_jobs WHERE label_source = ? ORDER BY id",
            (source,),
        ).fetchall()
        return [row["id"] for row in rows]

    def rows_by_source(self, source: str) -> list[dict]:
        """Return the labelled rows from one author, for the review document."""
        rows = self.conn.execute(
            "SELECT id, title, company, location, url, user_label, label_reason"
            " FROM scraped_jobs WHERE label_source = ? ORDER BY id",
            (source,),
        ).fetchall()
        return [dict(row) for row in rows]

    def count_by_source(self, source: str) -> int:
        """Count jobs currently carrying a label from one author."""
        return self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM scraped_jobs WHERE label_source = ?",
            (source,),
        ).fetchone()["cnt"]

    @staticmethod
    def _rejection_reason(
        entry: LabelEntry, state: dict[int, JobState], force: bool,
    ) -> str | None:
        """Return why this entry must not be written, or None if it may be."""
        if entry.label not in LABEL_VOCABULARY:
            return REASON_INVALID_LABEL
        if entry.job_id not in state:
            return REASON_UNKNOWN_JOB
        job = state[entry.job_id]
        # Checked before ``force``: force overrides a label, never the user's cancel.
        if entry.label in job.rejected:
            return REASON_PREVIOUSLY_REJECTED
        if job.user_label is not None and not force:
            return REASON_ALREADY_LABELED
        return None

    @staticmethod
    def _pass_refusal(entry: LabelEntry, state: dict[int, JobState]) -> str | None:
        """Return why this hand-back must not be written, or None if it may be."""
        if not (entry.reason or "").strip():
            return REASON_MISSING_REASON
        if entry.job_id not in state:
            return REASON_UNKNOWN_JOB
        job = state[entry.job_id]
        if job.user_label is not None:
            return REASON_ALREADY_LABELED
        if job.ai_passed_at is not None:
            return REASON_ALREADY_PASSED
        return None

    def job_states(self, job_ids: list[int]) -> dict[int, JobState]:
        """Return {job_id: JobState} for the ids that exist.

        Absence from the mapping means the row does not exist. Rejections are fetched in
        the same chunked pass as the labels, so the guard costs no extra round trip.
        """
        unique_ids = list(dict.fromkeys(job_ids))
        found: dict[int, JobState] = {}
        for start in range(0, len(unique_ids), _ID_CHUNK_SIZE):
            chunk = unique_ids[start:start + _ID_CHUNK_SIZE]
            # Only the generated '?' placeholders are interpolated; every id is bound.
            placeholders = ",".join("?" * len(chunk))
            rejected = self.rejections.labels_for_chunk(chunk, placeholders)
            rows = self.conn.execute(
                "SELECT id, user_label, ai_passed_at FROM scraped_jobs"
                f" WHERE id IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                found[row["id"]] = JobState(
                    user_label=row["user_label"],
                    ai_passed_at=row["ai_passed_at"],
                    rejected=rejected.get(row["id"], frozenset()),
                )
        return found
