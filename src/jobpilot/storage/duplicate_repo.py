"""Grouping scraped jobs whose posting text is byte-identical.

The same posting is stored many times — 70 groups covering 168 rows on the live corpus —
and a run that reads every copy separately can reach different verdicts for text that is
word-for-word the same. Grouping lets one decision cover every copy.

Only the description groups rows. Title plus company would merge genuinely separate
openings: 86 of 116 such groups span more than one city, and a role posted in three cities
may be three real jobs. Identical words are the conservative key — if the words are the
same, the verdict should be the same.

A group is a statement about the *text*, which is all the criteria judge. Nothing here
merges, edits or deletes a row.

Kept out of ``label_repo.py`` so that file stays under the 300-line limit.
"""

import sqlite3

# Rows are grouped only on byte-identical description text above this length. Shorter
# text (a stub, a cookie banner, a consent notice) repeats across unrelated postings.
MIN_GROUPED_DESCRIPTION = 200

# The text itself is the key rather than a stored hash: SQLite groups on the description
# directly, so there is no hash column to maintain and nothing that can fall out of step.
# The default BINARY collation makes the comparison byte-for-byte.
_GROUPS_SQL = (
    "SELECT GROUP_CONCAT(id) AS ids FROM scraped_jobs"
    " WHERE description IS NOT NULL AND LENGTH(description) >= ?"
    " GROUP BY description HAVING COUNT(*) > 1"
)

DUPLICATE_OF_KEY = "duplicate_of"


class DuplicateRepository:
    """Finds the rows whose description text is byte-identical."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def groups(self) -> dict[int, list[int]]:
        """Return {representative id: the other ids} for every duplicate group.

        The representative is the lowest id — a stable choice, not a better row, and it
        carries no weight at apply time. Rows with a NULL, empty or short description
        never appear, and neither does a group of one.
        """
        groups: dict[int, list[int]] = {}
        rows = self.conn.execute(_GROUPS_SQL, (MIN_GROUPED_DESCRIPTION,)).fetchall()
        for row in rows:
            ids = sorted(int(job_id) for job_id in row["ids"].split(","))
            groups[ids[0]] = ids[1:]
        return groups

    def collapse(self, rows: list[dict]) -> list[dict]:
        """Return ``rows`` with every duplicate group represented exactly once.

        The kept row is the lowest id *present* and gains ``duplicate_of`` listing the
        copies it stands in for; those copies are dropped. The representative is
        recomputed among the rows given rather than taken from ``groups()``: a group
        whose lowest id is already decided must still show its undecided copies once, or
        they would be exported never and so decided never.
        """
        stands_for = self._stands_for({row["id"] for row in rows})
        dropped = {copy for copies in stands_for.values() for copy in copies}
        collapsed = []
        for row in rows:
            if row["id"] in dropped:
                continue
            copies = stands_for.get(row["id"])
            collapsed.append(row | {DUPLICATE_OF_KEY: copies} if copies else row)
        return collapsed

    def _stands_for(self, present: set[int]) -> dict[int, list[int]]:
        """Return {kept id: the copies it represents} among one set of row ids."""
        stands_for: dict[int, list[int]] = {}
        for representative, members in self.groups().items():
            copies = sorted(
                job_id for job_id in (representative, *members) if job_id in present
            )
            if len(copies) > 1:
                stands_for[copies[0]] = copies[1:]
        return stands_for
