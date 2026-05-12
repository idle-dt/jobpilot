"""ML model, prediction, and training data access."""

import sqlite3
from datetime import datetime

from jobpilot.storage.models import MLPrediction, ModelVersion


class MLRepository:
    """CRUD operations for ML models, predictions, and training data."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Model Versions ---

    def insert_model_version(self, mv: ModelVersion) -> int:
        """Insert a model version. Returns the new ID."""
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
        """Get all model versions for a type, newest first."""
        rows = self.conn.execute(
            "SELECT * FROM model_versions WHERE model_type = ? ORDER BY trained_at DESC",
            (model_type,),
        ).fetchall()
        return [self._row_to_model_version(r) for r in rows]

    def get_active_model(self, model_type: str) -> ModelVersion | None:
        """Get the active model for a type."""
        row = self.conn.execute(
            "SELECT * FROM model_versions WHERE model_type = ? AND is_active = TRUE LIMIT 1",
            (model_type,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_model_version(row)

    def get_model_version(self, model_id: int) -> ModelVersion | None:
        """Get a model version by ID."""
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

    def delete_old_model_versions(
        self, model_type: str, keep_ids: list[int],
    ) -> None:
        """Delete old model versions for a type, keeping specified IDs."""
        if not keep_ids:
            return
        placeholders = ",".join("?" * len(keep_ids))
        ids = self.conn.execute(
            f"SELECT id FROM model_versions WHERE model_type = ?"
            f" AND id NOT IN ({placeholders})",
            [model_type, *keep_ids],
        ).fetchall()
        for row in ids:
            self.conn.execute(
                "DELETE FROM ml_predictions WHERE model_version_id = ?",
                (row["id"],),
            )
        self.conn.execute(
            f"DELETE FROM model_versions WHERE model_type = ?"
            f" AND id NOT IN ({placeholders})",
            [model_type, *keep_ids],
        )
        self.conn.commit()

    def get_next_version(self, model_type: str) -> int:
        """Get the next version number for a model type."""
        row = self.conn.execute(
            "SELECT MAX(version) as mv FROM model_versions WHERE model_type = ?",
            (model_type,),
        ).fetchone()
        return (row["mv"] or 0) + 1

    def invalidate_active_models(self) -> int:
        """Deactivate all active models. Returns count of deactivated models."""
        cursor = self.conn.execute(
            "UPDATE model_versions SET is_active = FALSE WHERE is_active = TRUE"
        )
        self.conn.commit()
        count = cursor.rowcount
        if count > 0:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("model_invalidated_at", datetime.now().isoformat()),
            )
            self.conn.commit()
        return count

    def _row_to_model_version(self, row: sqlite3.Row) -> ModelVersion:
        """Convert a database row to a ModelVersion model."""
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

    # --- Predictions ---

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
        placeholders = ",".join(["?"] * len(item_ids))
        query = (
            "SELECT p.item_id, p.prediction, p.probability,"
            "       mv.algorithm, mv.model_type, mv.is_active"
            " FROM ml_predictions p"
            " JOIN model_versions mv ON p.model_version_id = mv.id"
            " WHERE p.item_type = ? AND p.item_id IN (" + placeholders + ")"
            " ORDER BY p.predicted_at DESC"
        )
        rows = self.conn.execute(
            query, [item_type] + item_ids,
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
        """Delete all predictions for a model version."""
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
        rows = self.conn.execute(
            """SELECT id as email_id, title as subject, description as body_text,
                      1 as label, 'scraped_job' as item_source
               FROM scraped_jobs WHERE user_label IS NOT NULL"""
        ).fetchall()
        for r in rows:
            data.append(dict(r))
        return data

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
        """Get the most recent training timestamp for a model type."""
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
