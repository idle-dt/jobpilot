"""Email, signal, and feedback data access."""

import sqlite3
from datetime import datetime

from jobpilot.storage.models import Email, ExtractedSignal, UserFeedback


class EmailRepository:
    """CRUD operations for emails, extracted signals, and user feedback."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Emails ---

    def insert_email(self, email: Email) -> None:
        """Insert an email, ignoring duplicates."""
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
        """Get a single email by ID."""
        row = self.conn.execute(
            "SELECT * FROM emails WHERE id = ?", (email_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_email(row)

    def get_emails_for_review(self, limit: int = 20) -> list[Email]:
        """Get processed job emails that haven't received feedback yet."""
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
        """Get classified emails, optionally filtered by classification."""
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
        """Update scoring results and mark as processed."""
        self.conn.execute(
            """UPDATE emails SET raw_score = ?, ml_score = ?,
            final_classification = ?, confidence = ?, processed = TRUE
            WHERE id = ?""",
            (raw_score, ml_score, classification, confidence, email_id),
        )
        self.conn.commit()

    def update_email_origin_url(self, email_id: str, origin_url: str) -> None:
        """Set the origin URL for a single-job email."""
        self.conn.execute(
            "UPDATE emails SET origin_url = ? WHERE id = ?",
            (origin_url, email_id),
        )
        self.conn.commit()

    def get_unprocessed_emails(self) -> list[dict]:
        """Get emails that haven't been processed yet (id, subject, body_text)."""
        rows = self.conn.execute(
            "SELECT id, subject, body_text FROM emails WHERE processed = FALSE"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_emails_needing_origin_url(self) -> list[Email]:
        """Get emails that don't have an origin URL set."""
        rows = self.conn.execute(
            "SELECT * FROM emails WHERE origin_url IS NULL"
        ).fetchall()
        return [self._row_to_email(r) for r in rows]

    def get_all_processed_emails(self) -> list[dict]:
        """Get all processed emails (id, subject, body_text) for ML predictions."""
        rows = self.conn.execute(
            "SELECT id, subject, body_text FROM emails WHERE processed = TRUE"
        ).fetchall()
        return [dict(r) for r in rows]

    def _row_to_email(self, row: sqlite3.Row) -> Email:
        """Convert a database row to an Email model."""
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
        """Insert an extracted signal."""
        self.conn.execute(
            """INSERT INTO extracted_signals (email_id, signal_type, signal_value, confidence)
            VALUES (?, ?, ?, ?)""",
            (signal.email_id, signal.signal_type, signal.signal_value, signal.confidence),
        )
        self.conn.commit()

    def get_signals_for_email(self, email_id: str) -> list[ExtractedSignal]:
        """Get all signals for a given email."""
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
        """Insert user feedback for an email."""
        self.conn.execute(
            """INSERT INTO user_feedback (email_id, label, notes)
            VALUES (?, ?, ?)""",
            (feedback.email_id, feedback.label, feedback.notes),
        )
        self.conn.commit()

    def get_all_feedback(self) -> list[UserFeedback]:
        """Get all feedback entries ordered by most recent."""
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

    def delete_feedback(self, email_id: str) -> None:
        """Delete the most recent feedback for an email."""
        self.conn.execute(
            """DELETE FROM user_feedback WHERE id = (
                SELECT id FROM user_feedback WHERE email_id = ?
                ORDER BY feedback_at DESC LIMIT 1
            )""",
            (email_id,),
        )
        self.conn.commit()

    def count_feedback(self) -> int:
        """Count total feedback entries."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM user_feedback").fetchone()
        return row["cnt"]
