"""Dashboard statistics data access."""

import sqlite3
from datetime import datetime, timedelta

HISTOGRAM_BINS = 10
TREND_LOOKBACK_DAYS = 30
TOP_LOCATIONS_LIMIT = 10


class StatsRepository:
    """Dashboard statistics queries, decomposed into focused methods."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_email_stats(self) -> dict:
        """Get email overview statistics."""
        total = self.conn.execute("SELECT COUNT(*) as cnt FROM emails").fetchone()["cnt"]
        processed = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM emails WHERE processed = TRUE"
        ).fetchone()["cnt"]
        labeled = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM user_feedback"
        ).fetchone()["cnt"]
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
        """Get the most recent email received_at timestamp."""
        row = self.conn.execute(
            "SELECT MAX(received_at) as last_sync FROM emails"
        ).fetchone()
        if row and row["last_sync"]:
            return datetime.fromisoformat(row["last_sync"])
        return None

    def get_dashboard_stats(self, score_threshold: float = 0.6) -> dict:
        """Aggregate all dashboard statistics in one call."""
        return {
            **self._overview_stats(),
            **self._source_stats(),
            **self._classification_stats(),
            **self._label_stats(),
            **self._ml_readiness_stats(),
            **self._active_model_stats(),
            **self._score_histograms(score_threshold),
            **self._agreement_stats(),
            **self._trend_stats(),
            **self._location_stats(),
            **self._all_model_stats(),
            "recent_predictions": self._recent_predictions(),
            "recent_noise_predictions": self._recent_noise_predictions(),
        }

    def _overview_stats(self) -> dict:
        """Overview strip: totals, last sync, expired count."""
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
        email_label_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM user_feedback"
        ).fetchone()["cnt"]
        scraped_label_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE user_label IS NOT NULL"
        ).fetchone()["cnt"]
        return {
            "total_emails": total_emails,
            "total_jobs": total_jobs,
            "last_sync": last_sync.isoformat() if last_sync else None,
            "expired_count": expired_count,
            "expired_total": total_jobs,
            "labels_given": email_label_count + scraped_label_count,
        }

    def _source_stats(self) -> dict:
        """Jobs by source donut chart data."""
        rows = self.conn.execute(
            "SELECT source, COUNT(*) as cnt FROM scraped_jobs GROUP BY source"
            " ORDER BY cnt DESC"
        ).fetchall()
        return {"jobs_by_source": {r["source"]: r["cnt"] for r in rows}}

    def _classification_stats(self) -> dict:
        """Jobs by classification donut chart data."""
        rows = self.conn.execute(
            "SELECT classification, COUNT(*) as cnt FROM scraped_jobs"
            " GROUP BY classification"
        ).fetchall()
        return {"jobs_by_classification": {r["classification"]: r["cnt"] for r in rows}}

    def _label_stats(self) -> dict:
        """User labels donut chart — merged email feedback + scraped job labels."""
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
        return {"user_labels": user_labels}

    def _ml_readiness_stats(self) -> dict:
        """ML readiness indicators: label counts for each model type."""
        noise_email_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM user_feedback"
        ).fetchone()["cnt"]
        noise_scraped_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM scraped_jobs WHERE user_label IS NOT NULL"
        ).fetchone()["cnt"]
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
        return {
            "noise_label_count": noise_email_count + noise_scraped_count,
            "noise_negative_count": noise_negative_count,
            "scoring_label_count": scoring_feedback + scoring_scraped,
            "noise_tier1_min": 30,
            "noise_tier2_min": 60,
        }

    def _active_model_stats(self) -> dict:
        """Active model info per type."""
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
        return {"active_models": active_models}

    def _score_histograms(self, score_threshold: float) -> dict:
        """Score and confidence histogram bin data."""
        score_rows = self.conn.execute(
            "SELECT score FROM scraped_jobs WHERE score IS NOT NULL"
        ).fetchall()
        score_bins = [0] * HISTOGRAM_BINS
        confidence_bins = [0] * HISTOGRAM_BINS
        for r in score_rows:
            s = r["score"]
            score_bins[min(int(s * HISTOGRAM_BINS), HISTOGRAM_BINS - 1)] += 1
            conf = min(abs(s - score_threshold) / 0.4, 1.0)
            confidence_bins[min(int(conf * HISTOGRAM_BINS), HISTOGRAM_BINS - 1)] += 1
        return {
            "score_bins": score_bins,
            "score_threshold": score_threshold,
            "confidence_bins": confidence_bins,
        }

    def _agreement_stats(self) -> dict:
        """Agreement between rules and user labels."""
        rows = self.conn.execute(
            "SELECT classification, user_label FROM scraped_jobs"
            " WHERE classification IN ('worth_checking', 'skip')"
            " AND user_label IN ('worth_checking', 'skip')"
        ).fetchall()
        tp = fp = fn = tn = 0
        for r in rows:
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
        return {
            "agreement": {
                "total": total_compared,
                "agreed": agreed,
                "percentage": round(agreed / total_compared * 100, 1) if total_compared else 0,
                "matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            },
        }

    def _trend_stats(self) -> dict:
        """Jobs per day for the last N days."""
        trend_cutoff = (datetime.now() - timedelta(days=TREND_LOOKBACK_DAYS)).isoformat()
        rows = self.conn.execute(
            "SELECT DATE(scraped_at) as day, COUNT(*) as cnt FROM scraped_jobs"
            " WHERE scraped_at >= ?"
            " GROUP BY DATE(scraped_at) ORDER BY day",
            (trend_cutoff,),
        ).fetchall()
        return {
            "jobs_per_day": [{"date": r["day"], "count": r["cnt"]} for r in rows],
        }

    def _location_stats(self) -> dict:
        """Top job locations."""
        rows = self.conn.execute(
            "SELECT location, COUNT(*) as cnt FROM scraped_jobs"
            " WHERE location IS NOT NULL AND location != ''"
            " GROUP BY location ORDER BY cnt DESC LIMIT ?",
            (TOP_LOCATIONS_LIMIT,),
        ).fetchall()
        return {
            "top_locations": [
                {"location": r["location"], "count": r["cnt"]}
                for r in rows
            ],
        }

    def _all_model_stats(self) -> dict:
        """All model versions for experiment lab."""
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
        return {"all_models": all_models}

    def _recent_predictions(self) -> list[dict]:
        """Recent labeled items with model predictions for comparison."""
        items = []
        fb_rows = self.conn.execute(
            """SELECT uf.email_id as item_id, 'email' as item_type,
                      e.subject as title, uf.label as user_label,
                      uf.feedback_at as labeled_at, e.raw_score,
                      e.origin_url as url
               FROM user_feedback uf
               JOIN emails e ON uf.email_id = e.id
               WHERE uf.label IN ('worth_checking', 'skip')
               ORDER BY uf.feedback_at DESC LIMIT 20""",
        ).fetchall()
        for r in fb_rows:
            items.append(dict(r))
        sj_rows = self.conn.execute(
            """SELECT CAST(id AS TEXT) as item_id, 'scraped_job' as item_type,
                      title, user_label, labeled_at, score as raw_score, url
               FROM scraped_jobs
               WHERE user_label IN ('worth_checking', 'skip')
               ORDER BY labeled_at DESC LIMIT 20""",
        ).fetchall()
        for r in sj_rows:
            items.append(dict(r))
        items.sort(key=lambda x: x.get("labeled_at") or "", reverse=True)
        items = items[:20]

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

    def _recent_noise_predictions(self) -> list[dict]:
        """Recent labeled items with noise model predictions for comparison."""
        items = []
        fb_rows = self.conn.execute(
            """SELECT uf.email_id as item_id, 'email' as item_type,
                      e.subject as title, uf.label as user_label,
                      uf.feedback_at as labeled_at, e.origin_url as url
               FROM user_feedback uf
               JOIN emails e ON uf.email_id = e.id
               ORDER BY uf.feedback_at DESC LIMIT 20""",
        ).fetchall()
        for r in fb_rows:
            item = dict(r)
            item["noise_label"] = (
                "not_a_job" if item["user_label"] == "not_a_job" else "job"
            )
            items.append(item)
        sj_rows = self.conn.execute(
            """SELECT CAST(id AS TEXT) as item_id, 'scraped_job' as item_type,
                      title, user_label, labeled_at, url
               FROM scraped_jobs
               WHERE user_label IS NOT NULL
               ORDER BY labeled_at DESC LIMIT 20""",
        ).fetchall()
        for r in sj_rows:
            item = dict(r)
            item["noise_label"] = (
                "not_a_job" if item["user_label"] == "not_a_job" else "job"
            )
            items.append(item)
        items.sort(key=lambda x: x.get("labeled_at") or "", reverse=True)
        items = items[:20]

        for item in items:
            preds = self.conn.execute(
                """SELECT mv.algorithm, p.prediction, p.probability
                   FROM ml_predictions p
                   JOIN model_versions mv ON p.model_version_id = mv.id
                   WHERE p.item_type = ? AND p.item_id = ?
                     AND mv.model_type = 'noise'""",
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
