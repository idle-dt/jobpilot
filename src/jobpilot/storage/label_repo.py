"""Bulk label writes and source-scoped reverts for scraped jobs.

Kept out of job_repo.py, which is already over the 300-line limit. The single
source of truth for who authored a label is ``scraped_jobs.label_source``:
``'user'`` for a click in the UI, ``'assistant'`` for a ``label-batch`` run, and
NULL while the job is unlabeled. It says nothing about correctness, and it is
unrelated to ``ml_predictions`` — an assistant label is not a model prediction.
"""

import sqlite3
from dataclasses import dataclass, field

LABEL_VOCABULARY = ("worth_checking", "skip", "not_a_job")
ASSISTANT_SOURCE = "assistant"
USER_SOURCE = "user"

# Rejection reasons. A rejection writes nothing: the job stays in the queue
# exactly as it was, which is not the same as labeling it 'skip'.
REASON_UNKNOWN_JOB = "unknown job"
REASON_INVALID_LABEL = "invalid label"
REASON_ALREADY_LABELED = "already labeled"

# SQLite's default parameter limit is 999; chunk IN clauses well below it.
_ID_CHUNK_SIZE = 500

_APPLY_LABEL_SQL = (
    "UPDATE scraped_jobs SET user_label = ?, label_source = ?, label_reason = ?,"
    " labeled_at = datetime('now') WHERE id = ?"
)
_CLEAR_BY_SOURCE_SQL = (
    "UPDATE scraped_jobs SET user_label = NULL, labeled_at = NULL,"
    " label_source = NULL, label_reason = NULL WHERE label_source = ?"
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
        existing = self._existing_labels([e.job_id for e in entries])
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
        entry: LabelEntry, existing: dict[int, str | None], force: bool,
    ) -> str | None:
        """Return why this entry must not be written, or None if it may be."""
        if entry.label not in LABEL_VOCABULARY:
            return REASON_INVALID_LABEL
        if entry.job_id not in existing:
            return REASON_UNKNOWN_JOB
        if existing[entry.job_id] is not None and not force:
            return REASON_ALREADY_LABELED
        return None

    def _existing_labels(self, job_ids: list[int]) -> dict[int, str | None]:
        """Return {job_id: current user_label} for the ids that exist.

        Absence from the mapping means the row does not exist; a None value means
        the row exists and is unlabeled.
        """
        unique_ids = list(dict.fromkeys(job_ids))
        found: dict[int, str | None] = {}
        for start in range(0, len(unique_ids), _ID_CHUNK_SIZE):
            chunk = unique_ids[start:start + _ID_CHUNK_SIZE]
            # Only the generated '?' placeholders are interpolated; every id is bound.
            placeholders = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT id, user_label FROM scraped_jobs WHERE id IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                found[row["id"]] = row["user_label"]
        return found
