"""CRUD operations for all database tables."""

import sqlite3
from datetime import datetime

from jobpilot.storage.models import (
    Application,
    ApplicationStatusHistory,
    Email,
    ExtractedSignal,
    MLPrediction,
    ModelVersion,
    ScrapedJob,
    UserFeedback,
    UserPreference,
)

HISTOGRAM_BINS = 10
TREND_LOOKBACK_DAYS = 30
TOP_LOCATIONS_LIMIT = 10


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

    def update_scraped_job_label(self, job_id: int, label: str | None) -> None:
        labeled_at = "datetime('now')" if label else "NULL"
        self.conn.execute(
            f"UPDATE scraped_jobs SET user_label = ?, labeled_at = {labeled_at}"
            " WHERE id = ?",
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
            AND ABS(score - ?) / 0.4 < ?  -- 0.4 = CONFIDENCE_DIVISOR from rules.py
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

    def update_application_status(
        self, app_id: int, new_status: str, notes: str | None = None,
    ) -> None:
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

    # --- User Preferences ---

    def insert_preference(self, category: str, value: str, extra: str | None = None) -> int | None:
        """Insert a preference. Returns id if inserted, None if duplicate."""
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO user_preferences (category, value, extra) VALUES (?, ?, ?)",
            (category, value, extra),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            return None
        return cursor.lastrowid

    def delete_preference(self, category: str, value: str) -> bool:
        """Delete a preference. Returns True if deleted."""
        cursor = self.conn.execute(
            "DELETE FROM user_preferences WHERE category = ? AND value = ?",
            (category, value),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_preferences(self, category: str) -> list[UserPreference]:
        """Get all preferences for a category."""
        rows = self.conn.execute(
            "SELECT * FROM user_preferences WHERE category = ? ORDER BY value",
            (category,),
        ).fetchall()
        return [
            UserPreference(
                id=r["id"], category=r["category"], value=r["value"],
                extra=r["extra"], created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_all_preferences(self) -> dict[str, list[UserPreference]]:
        """Get all preferences grouped by category."""
        rows = self.conn.execute(
            "SELECT * FROM user_preferences ORDER BY category, value"
        ).fetchall()
        result: dict[str, list[UserPreference]] = {}
        for r in rows:
            pref = UserPreference(
                id=r["id"], category=r["category"], value=r["value"],
                extra=r["extra"], created_at=r["created_at"],
            )
            result.setdefault(r["category"], []).append(pref)
        return result

    def get_active_domains(self) -> list[str]:
        """Get all monitored domain values."""
        rows = self.conn.execute(
            "SELECT value FROM user_preferences WHERE category = 'monitored_domain' ORDER BY value"
        ).fetchall()
        return [r["value"] for r in rows]

    def count_preferences(self) -> int:
        """Count total preferences."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM user_preferences").fetchone()
        return row["cnt"]

    def invalidate_active_models(self) -> int:
        """Deactivate all active models. Returns count of deactivated models."""
        cursor = self.conn.execute(
            "UPDATE model_versions SET is_active = FALSE WHERE is_active = TRUE"
        )
        self.conn.commit()
        count = cursor.rowcount
        if count > 0:
            self.set_setting("model_invalidated_at", datetime.now().isoformat())
        return count

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

    # --- ML Models ---

    def insert_model_version(self, mv: ModelVersion) -> int:
        cursor = self.conn.execute(
            """INSERT INTO model_versions
            (version, training_samples, accuracy, precision_score, recall_score,
             f1_score, model_blob, feature_names, is_active, model_type, algorithm,
             train_accuracy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mv.version, mv.training_samples, mv.accuracy, mv.precision_score,
             mv.recall_score, mv.f1_score, mv.model_blob, mv.feature_names,
             mv.is_active, mv.model_type, mv.algorithm, mv.train_accuracy),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_model_versions_by_type(self, model_type: str) -> list[ModelVersion]:
        rows = self.conn.execute(
            "SELECT * FROM model_versions WHERE model_type = ? ORDER BY trained_at DESC",
            (model_type,),
        ).fetchall()
        return [self._row_to_model_version(r) for r in rows]

    def get_active_model(self, model_type: str) -> ModelVersion | None:
        row = self.conn.execute(
            "SELECT * FROM model_versions WHERE model_type = ? AND is_active = TRUE LIMIT 1",
            (model_type,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_model_version(row)

    def get_model_version(self, model_id: int) -> ModelVersion | None:
        row = self.conn.execute(
            "SELECT * FROM model_versions WHERE id = ?", (model_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_model_version(row)

    def activate_model(self, model_type: str, algorithm: str) -> None:
        """Deactivate all models of this type, then activate the matching one."""
        self.conn.execute(
            "UPDATE model_versions SET is_active = FALSE WHERE model_type = ?",
            (model_type,),
        )
        self.conn.execute(
            """UPDATE model_versions SET is_active = TRUE
            WHERE model_type = ? AND algorithm = ?
            ORDER BY trained_at DESC LIMIT 1""",
            (model_type, algorithm),
        )
        self.conn.commit()

    def activate_model_by_id(self, model_id: int, model_type: str) -> None:
        """Deactivate all models of this type, then activate the specified one."""
        self.conn.execute(
            "UPDATE model_versions SET is_active = FALSE WHERE model_type = ?",
            (model_type,),
        )
        self.conn.execute(
            "UPDATE model_versions SET is_active = TRUE WHERE id = ?",
            (model_id,),
        )
        self.conn.commit()

    def delete_model_versions_by_type(self, model_type: str) -> None:
        """Delete all model versions and their predictions for a model type."""
        ids = self.conn.execute(
            "SELECT id FROM model_versions WHERE model_type = ?",
            (model_type,),
        ).fetchall()
        for row in ids:
            self.conn.execute(
                "DELETE FROM ml_predictions WHERE model_version_id = ?",
                (row["id"],),
            )
        self.conn.execute(
            "DELETE FROM model_versions WHERE model_type = ?",
            (model_type,),
        )
        self.conn.commit()

    def get_next_version(self, model_type: str) -> int:
        row = self.conn.execute(
            "SELECT MAX(version) as mv FROM model_versions WHERE model_type = ?",
            (model_type,),
        ).fetchone()
        return (row["mv"] or 0) + 1

    def _row_to_model_version(self, row: sqlite3.Row) -> ModelVersion:
        return ModelVersion(
            id=row["id"], version=row["version"],
            training_samples=row["training_samples"],
            model_blob=row["model_blob"],
            trained_at=datetime.fromisoformat(row["trained_at"]) if row["trained_at"] else None,
            accuracy=row["accuracy"], precision_score=row["precision_score"],
            recall_score=row["recall_score"], f1_score=row["f1_score"],
            feature_names=row["feature_names"], is_active=bool(row["is_active"]),
            model_type=row["model_type"], algorithm=row["algorithm"],
            train_accuracy=row["train_accuracy"],
        )

    # --- ML Predictions ---

    def insert_predictions(self, predictions: list[MLPrediction]) -> None:
        """Bulk insert predictions."""
        self.conn.executemany(
            """INSERT INTO ml_predictions
            (model_version_id, item_type, item_id, prediction, probability)
            VALUES (?, ?, ?, ?, ?)""",
            [(p.model_version_id, p.item_type, p.item_id, p.prediction, p.probability)
             for p in predictions],
        )
        self.conn.commit()

    def get_predictions_for_items(
        self, item_type: str, item_ids: list[str]
    ) -> dict[str, list[dict]]:
        """Return predictions grouped by item_id, each with algorithm and probability."""
        if not item_ids:
            return {}
        placeholders = ",".join("?" * len(item_ids))
        rows = self.conn.execute(
            f"""SELECT p.item_id, p.prediction, p.probability,
                       mv.algorithm, mv.model_type, mv.is_active
                FROM ml_predictions p
                JOIN model_versions mv ON p.model_version_id = mv.id
                WHERE p.item_type = ? AND p.item_id IN ({placeholders})
                ORDER BY p.predicted_at DESC""",
            [item_type] + item_ids,
        ).fetchall()
        result: dict[str, list[dict]] = {}
        for r in rows:
            result.setdefault(r["item_id"], []).append({
                "algorithm": r["algorithm"],
                "model_type": r["model_type"],
                "prediction": r["prediction"],
                "probability": r["probability"],
                "is_active": bool(r["is_active"]),
            })
        return result

    def delete_predictions_for_model(self, model_version_id: int) -> None:
        self.conn.execute(
            "DELETE FROM ml_predictions WHERE model_version_id = ?",
            (model_version_id,),
        )
        self.conn.commit()

    # --- Training Data ---

    def get_noise_training_data(self) -> list[dict]:
        """Get training data for the noise model.

        Positive (1) = any feedback that is NOT 'not_a_job' + all labeled scraped jobs.
        Negative (0) = feedback with label 'not_a_job'.
        """
        data = []
        rows = self.conn.execute(
            """SELECT e.id as email_id, e.subject, e.body_text,
                      CASE WHEN uf.label = 'not_a_job' THEN 0 ELSE 1 END as label,
                      'email' as item_source
               FROM user_feedback uf
               JOIN emails e ON uf.email_id = e.id"""
        ).fetchall()
        for r in rows:
            data.append(dict(r))
        # Scraped jobs are always job-related (positive class)
        rows = self.conn.execute(
            """SELECT id as email_id, title as subject, description as body_text,
                      1 as label, 'scraped_job' as item_source
               FROM scraped_jobs WHERE user_label IS NOT NULL"""
        ).fetchall()
        for r in rows:
            data.append(dict(r))
        return data

    def count_scraped_jobs_for_email(self, email_id) -> int:
        """Count scraped jobs linked to an email (for digest_job_count feature)."""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE email_id = ?",
            (str(email_id),),
        ).fetchone()
        return row["cnt"] if row else 0

    def get_scoring_training_data(self) -> list[dict]:
        """Get training data for the scoring model.

        From user_feedback: worth_checking=1, skip=0.
        From scraped_jobs: user_label worth_checking=1, skip=0.
        """
        data = []
        rows = self.conn.execute(
            """SELECT e.id as item_id, e.subject, e.body_text as body,
                      CASE WHEN uf.label = 'worth_checking' THEN 1 ELSE 0 END as label
               FROM user_feedback uf
               JOIN emails e ON uf.email_id = e.id
               WHERE uf.label IN ('worth_checking', 'skip')"""
        ).fetchall()
        for r in rows:
            data.append({"item_type": "email", "item_id": r["item_id"],
                         "subject": r["subject"], "body": r["body"] or "", "label": r["label"]})
        rows = self.conn.execute(
            """SELECT id as item_id, title, company, location, description,
                      CASE WHEN user_label = 'worth_checking' THEN 1 ELSE 0 END as label
               FROM scraped_jobs
               WHERE user_label IN ('worth_checking', 'skip')"""
        ).fetchall()
        for r in rows:
            body = (
                f"{r['title']} {r['company'] or ''}"
                f" {r['location'] or ''} {r['description'] or ''}"
            )
            data.append({
                "item_type": "scraped_job", "item_id": str(r["item_id"]),
                "subject": r["title"], "body": body, "label": r["label"],
            })
        return data

    def get_last_training_time(self, model_type: str) -> str | None:
        row = self.conn.execute(
            "SELECT MAX(trained_at) as t FROM model_versions WHERE model_type = ?",
            (model_type,),
        ).fetchone()
        return row["t"] if row and row["t"] else None

    def count_labels_since(self, since_timestamp: str | None) -> int:
        """Count feedback + scraped labels given since a timestamp."""
        if not since_timestamp:
            fb = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM user_feedback"
            ).fetchone()["cnt"]
            sj = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE user_label IS NOT NULL"
            ).fetchone()["cnt"]
            return fb + sj
        fb = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM user_feedback WHERE feedback_at > ?",
            (since_timestamp,),
        ).fetchone()["cnt"]
        sj = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE labeled_at > ?",
            (since_timestamp,),
        ).fetchone()["cnt"]
        return fb + sj

    def get_recent_predictions_comparison(self, limit: int = 20) -> list[dict]:
        """Get last N labeled items with all model predictions for comparison."""
        items = []
        fb_rows = self.conn.execute(
            """SELECT uf.email_id as item_id, 'email' as item_type,
                      e.subject as title, uf.label as user_label,
                      uf.feedback_at as labeled_at, e.raw_score,
                      e.origin_url as url
               FROM user_feedback uf
               JOIN emails e ON uf.email_id = e.id
               WHERE uf.label IN ('worth_checking', 'skip')
               ORDER BY uf.feedback_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        for r in fb_rows:
            items.append(dict(r))
        sj_rows = self.conn.execute(
            """SELECT CAST(id AS TEXT) as item_id, 'scraped_job' as item_type,
                      title, user_label, labeled_at, score as raw_score, url
               FROM scraped_jobs
               WHERE user_label IN ('worth_checking', 'skip')
               ORDER BY labeled_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        for r in sj_rows:
            items.append(dict(r))
        items.sort(key=lambda x: x.get("labeled_at") or "", reverse=True)
        items = items[:limit]

        for item in items:
            preds = self.conn.execute(
                """SELECT mv.algorithm, mv.model_type, p.prediction, p.probability
                   FROM ml_predictions p
                   JOIN model_versions mv ON p.model_version_id = mv.id
                   WHERE p.item_type = ? AND p.item_id = ?""",
                (item["item_type"], item["item_id"]),
            ).fetchall()
            item["predictions"] = {
                r["algorithm"]: {
                    "prediction": r["prediction"],
                    "probability": r["probability"],
                }
                for r in preds
            }
        return items

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

    def get_dashboard_stats(self, score_threshold: float = 0.6) -> dict:
        """Aggregate all dashboard statistics in one call."""
        # Overview strip
        total_emails = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM emails"
        ).fetchone()["cnt"]
        total_jobs = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs"
        ).fetchone()["cnt"]
        last_sync = self.get_last_sync_time()
        expired_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE expired = TRUE"
        ).fetchone()["cnt"]
        email_label_count = self.count_feedback()
        scraped_label_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE user_label IS NOT NULL"
        ).fetchone()["cnt"]

        # Sources donut
        source_rows = self.conn.execute(
            "SELECT source, COUNT(*) as cnt FROM scraped_jobs GROUP BY source"
            " ORDER BY cnt DESC"
        ).fetchall()

        # Classification donut
        class_rows = self.conn.execute(
            "SELECT classification, COUNT(*) as cnt FROM scraped_jobs"
            " GROUP BY classification"
        ).fetchall()

        # User labels donut — merge email feedback + scraped job labels
        feedback_rows = self.conn.execute(
            "SELECT label, COUNT(*) as cnt FROM user_feedback GROUP BY label"
        ).fetchall()
        scraped_label_rows = self.conn.execute(
            "SELECT user_label, COUNT(*) as cnt FROM scraped_jobs"
            " WHERE user_label IS NOT NULL GROUP BY user_label"
        ).fetchall()
        user_labels: dict[str, int] = {}
        for r in feedback_rows:
            user_labels[r["label"]] = user_labels.get(r["label"], 0) + r["cnt"]
        for r in scraped_label_rows:
            user_labels[r["user_label"]] = (
                user_labels.get(r["user_label"], 0) + r["cnt"]
            )

        # ML readiness
        noise_email_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM user_feedback"
        ).fetchone()["cnt"]
        noise_scraped_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE user_label IS NOT NULL"
        ).fetchone()["cnt"]
        noise_label_count = noise_email_count + noise_scraped_count
        noise_negative_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM user_feedback WHERE label = 'not_a_job'"
        ).fetchone()["cnt"]
        scoring_feedback = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM user_feedback"
            " WHERE label IN ('worth_checking', 'skip')"
        ).fetchone()["cnt"]
        scoring_scraped = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs"
            " WHERE user_label IN ('worth_checking', 'skip')"
        ).fetchone()["cnt"]
        scoring_label_count = scoring_feedback + scoring_scraped

        # Active models (one per type)
        active_models = {}
        for mt in ("noise", "scoring"):
            row = self.conn.execute(
                "SELECT * FROM model_versions"
                " WHERE is_active = TRUE AND model_type = ? LIMIT 1",
                (mt,),
            ).fetchone()
            if row:
                active_models[mt] = {
                    "version": row["version"],
                    "algorithm": row["algorithm"],
                    "trained_at": row["trained_at"],
                    "training_samples": row["training_samples"],
                    "accuracy": row["accuracy"],
                    "precision": row["precision_score"],
                    "recall": row["recall_score"],
                    "f1": row["f1_score"],
                }

        # Score & confidence histograms
        score_rows = self.conn.execute(
            "SELECT score FROM scraped_jobs WHERE score IS NOT NULL"
        ).fetchall()
        score_bins = [0] * HISTOGRAM_BINS
        confidence_bins = [0] * HISTOGRAM_BINS
        for r in score_rows:
            s = r["score"]
            score_bins[min(int(s * HISTOGRAM_BINS), HISTOGRAM_BINS - 1)] += 1
            conf = min(abs(s - score_threshold) / 0.4, 1.0)  # 0.4 = CONFIDENCE_DIVISOR
            confidence_bins[min(int(conf * HISTOGRAM_BINS), HISTOGRAM_BINS - 1)] += 1

        # Agreement: rules vs user labels
        agreement_rows = self.conn.execute(
            "SELECT classification, user_label FROM scraped_jobs"
            " WHERE classification IN ('worth_checking', 'skip')"
            " AND user_label IN ('worth_checking', 'skip')"
        ).fetchall()
        tp = fp = fn = tn = 0
        for r in agreement_rows:
            rule, user = r["classification"], r["user_label"]
            if rule == "worth_checking" and user == "worth_checking":
                tp += 1
            elif rule == "worth_checking" and user == "skip":
                fp += 1
            elif rule == "skip" and user == "worth_checking":
                fn += 1
            else:
                tn += 1
        total_compared = tp + fp + fn + tn
        agreed = tp + tn
        agreement = {
            "total": total_compared,
            "agreed": agreed,
            "percentage": round(agreed / total_compared * 100, 1) if total_compared else 0,
            "matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        }

        # Jobs per day (last 30 days)
        trend_rows = self.conn.execute(
            "SELECT DATE(scraped_at) as day, COUNT(*) as cnt FROM scraped_jobs"
            f" WHERE scraped_at >= date('now', '-{TREND_LOOKBACK_DAYS} days')"
            " GROUP BY DATE(scraped_at) ORDER BY day"
        ).fetchall()

        # Top locations
        location_rows = self.conn.execute(
            "SELECT location, COUNT(*) as cnt FROM scraped_jobs"
            " WHERE location IS NOT NULL AND location != ''"
            f" GROUP BY location ORDER BY cnt DESC LIMIT {TOP_LOCATIONS_LIMIT}"
        ).fetchall()

        # All model versions for experiment lab
        all_models: dict[str, list[dict]] = {}
        for mt in ("noise", "scoring"):
            rows = self.conn.execute(
                "SELECT * FROM model_versions WHERE model_type = ?"
                " ORDER BY trained_at DESC",
                (mt,),
            ).fetchall()
            all_models[mt] = [
                {
                    "id": r["id"], "version": r["version"],
                    "algorithm": r["algorithm"],
                    "accuracy": r["accuracy"],
                    "precision": r["precision_score"],
                    "recall": r["recall_score"],
                    "f1": r["f1_score"],
                    "trained_at": r["trained_at"],
                    "training_samples": r["training_samples"],
                    "is_active": bool(r["is_active"]),
                    "feature_names": r["feature_names"],
                    "train_accuracy": r["train_accuracy"],
                }
                for r in rows
            ]

        recent_predictions = self.get_recent_predictions_comparison(limit=20)

        return {
            "total_emails": total_emails,
            "total_jobs": total_jobs,
            "last_sync": last_sync.isoformat() if last_sync else None,
            "expired_count": expired_count,
            "expired_total": total_jobs,
            "labels_given": email_label_count + scraped_label_count,
            "jobs_by_source": {r["source"]: r["cnt"] for r in source_rows},
            "jobs_by_classification": {
                r["classification"]: r["cnt"] for r in class_rows
            },
            "user_labels": user_labels,
            "noise_label_count": noise_label_count,
            "noise_negative_count": noise_negative_count,
            "scoring_label_count": scoring_label_count,
            "active_models": active_models,
            "score_bins": score_bins,
            "score_threshold": score_threshold,
            "confidence_bins": confidence_bins,
            "agreement": agreement,
            "jobs_per_day": [
                {"date": r["day"], "count": r["cnt"]} for r in trend_rows
            ],
            "top_locations": [
                {"location": r["location"], "count": r["cnt"]}
                for r in location_rows
            ],
            "noise_tier1_min": 30,  # from ml_trainer.NOISE_TIER1_MIN_LABELS
            "noise_tier2_min": 60,  # from ml_trainer.NOISE_TIER2_MIN_LABELS
            "all_models": all_models,
            "recent_predictions": recent_predictions,
        }
