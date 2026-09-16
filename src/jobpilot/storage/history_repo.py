"""Paged reads of every label currently in effect, for the History page.

Kept out of ``label_repo.py`` and ``job_repo.py``: the first is about writing verdicts and
the second is already over the 300-line limit. This module only reads, and only for
display.

Rows are ordered by ``datetime(labeled_at)`` rather than the raw column. The stored values
come in two shapes — 'T'-separated local timestamps written before the UTC fix, and
space-separated UTC ones written since — and because `' ' < 'T'`, a raw string sort puts
same-second rows in the wrong order. SQLite parses both shapes, so wrapping the column
normalises them.
"""

import sqlite3

# Each view maps to a hardcoded predicate. The request never reaches SQL: the route
# validates against these keys and the value here is a literal.
VIEW_PREDICATES = {
    "all": "user_label IS NOT NULL",
    "worth_checking": "user_label = 'worth_checking'",
    "skip": "user_label = 'skip'",
    "not_a_job": "user_label = 'not_a_job'",
    "assistant": "user_label IS NOT NULL AND label_source = 'assistant'",
}

_COLUMNS = (
    "id, title, company, location, url, user_label, label_source, label_reason, labeled_at"
)


class HistoryRepository:
    """Reads labeled scraped jobs for the History page."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def labeled_jobs(self, view: str, limit: int, offset: int) -> list[dict]:
        """Return one page of labeled jobs under a view, newest label first.

        ``view`` must be a key of VIEW_PREDICATES; callers validate it before arriving
        here, and only the literal predicate is interpolated.
        """
        predicate = VIEW_PREDICATES[view]
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM scraped_jobs WHERE {predicate}"
            " ORDER BY datetime(labeled_at) DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]

    def count_labeled_jobs(self, view: str) -> int:
        """Count the labeled jobs under one view."""
        predicate = VIEW_PREDICATES[view]
        return self.conn.execute(
            f"SELECT COUNT(*) AS cnt FROM scraped_jobs WHERE {predicate}",
        ).fetchone()["cnt"]
