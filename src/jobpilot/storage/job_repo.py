"""Scraped job data access."""

import sqlite3
from datetime import datetime

from jobpilot.storage.models import ScrapedJob


class JobRepository:
    """CRUD operations for scraped jobs."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_scraped_job(self, job: ScrapedJob) -> bool:
        """Insert a scraped job. Returns True if inserted, False if duplicate URL."""
        try:
            self.conn.execute(
                """INSERT INTO scraped_jobs
                (source, title, company, location, url, salary, posted_date, remote, email_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.source, job.title, job.company, job.location,
                    job.url, job.salary, job.posted_date, job.remote, job.email_id,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_scraped_jobs_for_review(self, limit: int = 20) -> list[ScrapedJob]:
        """Get scraped jobs that need user review."""
        rows = self.conn.execute(
            """SELECT * FROM scraped_jobs
            WHERE user_label IS NULL AND classification != 'skip'
            ORDER BY scraped_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_scraped_job(r) for r in rows]

    def update_scraped_job_label(self, job_id: int, label: str | None) -> None:
        """Set or clear the user label on a scraped job."""
        if label:
            self.conn.execute(
                "UPDATE scraped_jobs SET user_label = ?, labeled_at = ? WHERE id = ?",
                (label, datetime.now().isoformat(), job_id),
            )
        else:
            self.conn.execute(
                "UPDATE scraped_jobs SET user_label = NULL, labeled_at = NULL WHERE id = ?",
                (job_id,),
            )
        self.conn.commit()

    def update_scraped_job_scores(
        self, job_id: int, score: float, ml_score: float | None, classification: str
    ) -> None:
        """Update scoring results for a scraped job."""
        self.conn.execute(
            """UPDATE scraped_jobs SET score = ?, ml_score = ?, classification = ?
            WHERE id = ?""",
            (score, ml_score, classification, job_id),
        )
        self.conn.commit()

    def update_scraped_job_description(self, job_id: int, description: str) -> None:
        """Set the full job description text for a scraped job."""
        self.conn.execute(
            "UPDATE scraped_jobs SET description = ? WHERE id = ?",
            (description, job_id),
        )
        self.conn.commit()

    def mark_scrape_attempted(self, job_id: int) -> None:
        """Mark a scraped job as having had a scrape attempt."""
        self.conn.execute(
            "UPDATE scraped_jobs SET scrape_attempted = TRUE WHERE id = ?",
            (job_id,),
        )
        self.conn.commit()

    def get_jobs_needing_scrape(
        self, score_threshold: float, confidence_threshold: float
    ) -> list[ScrapedJob]:
        """Return scored jobs where confidence is below threshold and scrape not yet attempted."""
        rows = self.conn.execute(
            """SELECT * FROM scraped_jobs
            WHERE score IS NOT NULL
            AND scrape_attempted = FALSE
            AND ABS(score - ?) / 0.4 < ?
            ORDER BY ABS(score - ?) ASC""",
            (score_threshold, confidence_threshold, score_threshold),
        ).fetchall()
        return [self._row_to_scraped_job(r) for r in rows]

    def get_email_ids_with_extracted_jobs(self) -> set[str]:
        """Return email IDs that have extracted jobs in scraped_jobs."""
        rows = self.conn.execute(
            "SELECT DISTINCT email_id FROM scraped_jobs WHERE email_id IS NOT NULL"
        ).fetchall()
        return {r["email_id"] for r in rows}

    def toggle_scraped_job_expired(self, job_id: int) -> bool:
        """Toggle the expired flag. Returns the new value."""
        row = self.conn.execute(
            "SELECT expired FROM scraped_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            return False
        new_val = not bool(row["expired"])
        self.conn.execute(
            "UPDATE scraped_jobs SET expired = ? WHERE id = ?", (new_val, job_id)
        )
        self.conn.commit()
        return new_val

    def delete_scraped_jobs_for_email(self, email_id: str) -> int:
        """Delete all scraped jobs extracted from a given email. Returns count deleted."""
        cur = self.conn.execute(
            "DELETE FROM scraped_jobs WHERE email_id = ? AND user_label IS NULL",
            (email_id,),
        )
        self.conn.commit()
        return cur.rowcount

    def count_scraped_jobs_for_email(self, email_id) -> int:
        """Count scraped jobs linked to an email (for digest_job_count feature)."""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE email_id = ?",
            (str(email_id),),
        ).fetchone()
        return row["cnt"] if row else 0

    def get_pending_scraped_jobs(self) -> list[dict]:
        """Get scraped jobs with pending classification."""
        rows = self.conn.execute(
            "SELECT id, title, company, location, description"
            " FROM scraped_jobs WHERE classification = 'pending'"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_unlabeled_scraped_jobs(self) -> list[dict]:
        """Get scraped jobs without user labels (id, email_id, title)."""
        rows = self.conn.execute(
            "SELECT id, email_id, title FROM scraped_jobs WHERE user_label IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_scraped_jobs(self) -> list[dict]:
        """Get all scraped jobs (id, title, company, location, description) for ML predictions."""
        rows = self.conn.execute(
            "SELECT id, title, company, location, description FROM scraped_jobs"
        ).fetchall()
        return [dict(r) for r in rows]

    def _row_to_scraped_job(self, row: sqlite3.Row) -> ScrapedJob:
        """Convert a database row to a ScrapedJob model."""
        return ScrapedJob(
            id=row["id"], source=row["source"], title=row["title"],
            company=row["company"], location=row["location"], url=row["url"],
            salary=row["salary"], posted_date=row["posted_date"],
            remote=bool(row["remote"]), scraped_at=row["scraped_at"],
            score=row["score"], ml_score=row["ml_score"],
            classification=row["classification"], user_label=row["user_label"],
            labeled_at=row["labeled_at"], email_id=row["email_id"],
            expired=bool(row["expired"]),
            description=row["description"],
            scrape_attempted=bool(row["scrape_attempted"]),
        )
