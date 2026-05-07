"""CRUD operations for all database tables."""

import sqlite3
from datetime import datetime

from jobpilot.storage.models import (
    Application,
    ApplicationStatusHistory,
    Email,
    ExtractedSignal,
    ScrapedJob,
    UserFeedback,
)


class Repository:
    """Data access layer for JobPilot."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Emails ---

    def insert_email(self, email: Email) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO emails
            (id, thread_id, sender, sender_domain, subject, body_text, body_html,
             received_at, platform, is_job_related, raw_score, ml_score,
             final_classification, confidence, processed, origin_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email.id, email.thread_id, email.sender, email.sender_domain,
                email.subject, email.body_text, email.body_html,
                email.received_at.isoformat() if email.received_at else None,
                email.platform, email.is_job_related, email.raw_score,
                email.ml_score, email.final_classification, email.confidence,
                email.processed, email.origin_url,
            ),
        )
        self.conn.commit()

    def get_email(self, email_id: str) -> Email | None:
        row = self.conn.execute(
            "SELECT * FROM emails WHERE id = ?", (email_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_email(row)

    def get_emails_for_review(self, limit: int = 20) -> list[Email]:
        rows = self.conn.execute(
            """SELECT * FROM emails
            WHERE processed = TRUE AND final_classification IS NOT NULL
            AND is_job_related = TRUE
            AND id NOT IN (SELECT email_id FROM user_feedback)
            ORDER BY received_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_email(r) for r in rows]

    def get_emails_classified(
        self, classification: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Email]:
        if classification:
            rows = self.conn.execute(
                """SELECT * FROM emails WHERE final_classification = ?
                ORDER BY received_at DESC LIMIT ? OFFSET ?""",
                (classification, limit, offset),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM emails WHERE processed = TRUE
                ORDER BY received_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [self._row_to_email(r) for r in rows]

    def update_email_scores(
        self, email_id: str, raw_score: float, ml_score: float | None,
        classification: str, confidence: float | None
    ) -> None:
        self.conn.execute(
            """UPDATE emails SET raw_score = ?, ml_score = ?,
            final_classification = ?, confidence = ?, processed = TRUE
            WHERE id = ?""",
            (raw_score, ml_score, classification, confidence, email_id),
        )
        self.conn.commit()

    def _row_to_email(self, row: sqlite3.Row) -> Email:
        return Email(
            id=row["id"],
            thread_id=row["thread_id"],
            sender=row["sender"],
            sender_domain=row["sender_domain"],
            subject=row["subject"],
            body_text=row["body_text"],
            body_html=row["body_html"],
            received_at=datetime.fromisoformat(row["received_at"]) if row["received_at"] else None,
            fetched_at=datetime.fromisoformat(row["fetched_at"]) if row["fetched_at"] else None,
            platform=row["platform"],
            is_job_related=bool(row["is_job_related"]),
            raw_score=row["raw_score"],
            ml_score=row["ml_score"],
            final_classification=row["final_classification"],
            confidence=row["confidence"],
            processed=bool(row["processed"]),
            origin_url=row["origin_url"],
        )

    # --- Signals ---

    def insert_signal(self, signal: ExtractedSignal) -> None:
        self.conn.execute(
            """INSERT INTO extracted_signals (email_id, signal_type, signal_value, confidence)
            VALUES (?, ?, ?, ?)""",
            (signal.email_id, signal.signal_type, signal.signal_value, signal.confidence),
        )
        self.conn.commit()

    def get_signals_for_email(self, email_id: str) -> list[ExtractedSignal]:
        rows = self.conn.execute(
            "SELECT * FROM extracted_signals WHERE email_id = ?", (email_id,)
        ).fetchall()
        return [
            ExtractedSignal(
                id=r["id"], email_id=r["email_id"], signal_type=r["signal_type"],
                signal_value=r["signal_value"], confidence=r["confidence"],
            )
            for r in rows
        ]

    # --- Feedback ---

    def insert_feedback(self, feedback: UserFeedback) -> None:
        self.conn.execute(
            """INSERT INTO user_feedback (email_id, label, notes)
            VALUES (?, ?, ?)""",
            (feedback.email_id, feedback.label, feedback.notes),
        )
        self.conn.commit()

    def get_all_feedback(self) -> list[UserFeedback]:
        rows = self.conn.execute(
            "SELECT * FROM user_feedback ORDER BY feedback_at DESC"
        ).fetchall()
        return [
            UserFeedback(
                id=r["id"], email_id=r["email_id"], label=r["label"],
                feedback_at=datetime.fromisoformat(r["feedback_at"]) if r["feedback_at"] else None,
                notes=r["notes"],
            )
            for r in rows
        ]

    def count_feedback(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM user_feedback").fetchone()
        return row["cnt"]

    # --- Scraped Jobs ---

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
        rows = self.conn.execute(
            """SELECT * FROM scraped_jobs
            WHERE user_label IS NULL AND classification != 'skip'
            ORDER BY scraped_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_scraped_job(r) for r in rows]

    def update_scraped_job_label(self, job_id: int, label: str) -> None:
        self.conn.execute(
            """UPDATE scraped_jobs SET user_label = ?, labeled_at = datetime('now')
            WHERE id = ?""",
            (label, job_id),
        )
        self.conn.commit()

    def update_scraped_job_scores(
        self, job_id: int, score: float, ml_score: float | None, classification: str
    ) -> None:
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

    def _row_to_scraped_job(self, row: sqlite3.Row) -> ScrapedJob:
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

    def update_email_origin_url(self, email_id: str, origin_url: str) -> None:
        self.conn.execute(
            "UPDATE emails SET origin_url = ? WHERE id = ?",
            (origin_url, email_id),
        )
        self.conn.commit()

    # --- Applications ---

    def insert_application(self, app: Application) -> int:
        cursor = self.conn.execute(
            """INSERT INTO applications
            (email_id, scraped_job_id, company, role_title, location, salary_range,
             job_url, platform, track, status, contact_name, contact_email, notes,
             cover_letter_track, cv_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                app.email_id, app.scraped_job_id, app.company, app.role_title,
                app.location, app.salary_range, app.job_url, app.platform,
                app.track, app.status, app.contact_name, app.contact_email,
                app.notes, app.cover_letter_track, app.cv_version,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_application(self, app_id: int) -> Application | None:
        row = self.conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_application(row)

    def get_applications_by_status(self, status: str | None = None) -> list[Application]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY last_status_change DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM applications ORDER BY last_status_change DESC"
            ).fetchall()
        return [self._row_to_application(r) for r in rows]

    def update_application_status(self, app_id: int, new_status: str, notes: str | None = None) -> None:
        current = self.get_application(app_id)
        if not current:
            return
        self.conn.execute(
            """UPDATE applications SET status = ?, last_status_change = datetime('now'),
            updated_at = datetime('now') WHERE id = ?""",
            (new_status, app_id),
        )
        self.conn.execute(
            """INSERT INTO application_status_history
            (application_id, from_status, to_status, notes)
            VALUES (?, ?, ?, ?)""",
            (app_id, current.status, new_status, notes),
        )
        self.conn.commit()

    def get_application_history(self, app_id: int) -> list[ApplicationStatusHistory]:
        rows = self.conn.execute(
            "SELECT * FROM application_status_history WHERE application_id = ? ORDER BY changed_at",
            (app_id,),
        ).fetchall()
        return [
            ApplicationStatusHistory(
                id=r["id"], application_id=r["application_id"],
                from_status=r["from_status"], to_status=r["to_status"],
                changed_at=r["changed_at"], notes=r["notes"],
            )
            for r in rows
        ]

    def count_applications_by_status(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    def _row_to_application(self, row: sqlite3.Row) -> Application:
        return Application(
            id=row["id"], company=row["company"], role_title=row["role_title"],
            status=row["status"], email_id=row["email_id"],
            scraped_job_id=row["scraped_job_id"], location=row["location"],
            salary_range=row["salary_range"], job_url=row["job_url"],
            platform=row["platform"], track=row["track"],
            saved_at=row["saved_at"], applied_at=row["applied_at"],
            last_status_change=row["last_status_change"],
            contact_name=row["contact_name"], contact_email=row["contact_email"],
            notes=row["notes"], cover_letter_track=row["cover_letter_track"],
            cv_version=row["cv_version"], offer_salary=row["offer_salary"],
            offer_currency=row["offer_currency"], offer_equity=row["offer_equity"],
            offer_relocation_package=row["offer_relocation_package"],
            offer_notes=row["offer_notes"], created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Settings ---

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return row["value"]
        return default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    # --- Stats ---

    def get_email_stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) as cnt FROM emails").fetchone()["cnt"]
        processed = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM emails WHERE processed = TRUE"
        ).fetchone()["cnt"]
        labeled = self.count_feedback()
        by_platform = self.conn.execute(
            "SELECT platform, COUNT(*) as cnt FROM emails GROUP BY platform"
        ).fetchall()
        by_class = self.conn.execute(
            """SELECT final_classification, COUNT(*) as cnt FROM emails
            WHERE final_classification IS NOT NULL GROUP BY final_classification"""
        ).fetchall()
        noise_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM user_feedback WHERE label = 'not_a_job'"
        ).fetchone()["cnt"]
        return {
            "total": total,
            "processed": processed,
            "labeled": labeled,
            "noise_count": noise_count,
            "by_platform": {r["platform"]: r["cnt"] for r in by_platform},
            "by_classification": {r["final_classification"]: r["cnt"] for r in by_class},
        }

    def get_last_sync_time(self) -> datetime | None:
        row = self.conn.execute(
            "SELECT MAX(received_at) as last_sync FROM emails"
        ).fetchone()
        if row and row["last_sync"]:
            return datetime.fromisoformat(row["last_sync"])
        return None
