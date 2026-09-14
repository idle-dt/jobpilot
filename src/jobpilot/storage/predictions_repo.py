"""Recent predictions data access for scoring and noise models."""

import re
import sqlite3

from jobpilot.storage.label_repo import USER_SOURCE

EMAIL_ID_PATTERN = re.compile(r"^[a-f0-9]{10,20}$")
RECENT_PREDICTIONS_LIMIT = 20


def label_sort_key(timestamp: str | None) -> str:
    """Return a label timestamp normalised so the three stored formats compare.

    Label times arrive in three shapes: user_feedback.feedback_at (UTC, space
    separated), historical scraped_jobs.labeled_at (ISO-8601 with a 'T') and
    current labeled_at (UTC, space separated). Sorting the raw strings puts every
    'T' form above every space form for the same day, because ' ' < 'T' — so a
    10:28 hand label outranked a 12:31 bulk label. Swapping the separator makes
    all three lexicographically ordered, which for a fixed-width date-time prefix
    is the same as chronological.
    """
    return (timestamp or "").replace("T", " ")


class PredictionsRepository:
    """Fetches recent labeled items with ML model predictions."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def recent_scoring(self) -> list[dict]:
        """Recent labeled items with scoring model predictions."""
        items = self._fetch_labeled_items(
            email_label_filter="uf.label IN ('worth_checking', 'skip')",
            scraped_label_filter="user_label IN ('worth_checking', 'skip')",
            extra_email_cols=", e.raw_score",
        )
        self._attach_predictions(items)
        return items

    def recent_noise(self) -> list[dict]:
        """Recent labeled items with noise model predictions (emails only)."""
        items = self._fetch_labeled_items(
            email_label_filter="1=1",
            scraped_label_filter="1=0",
        )
        for item in items:
            item["noise_label"] = (
                "not_a_job" if item["user_label"] == "not_a_job" else "job"
            )
        self._attach_predictions(items, model_type="noise")
        return items

    def _fetch_labeled_items(
        self,
        email_label_filter: str,
        scraped_label_filter: str,
        extra_email_cols: str = "",
    ) -> list[dict]:
        """Fetch recent labeled emails and scraped jobs, merged and sorted.

        Warning: filter args are raw SQL fragments for internal use only.
        Callers must pass hardcoded strings — never user input.
        """
        items = []
        # Email feedback is always hand-authored — there is no bulk path to it —
        # so the user source is bound in rather than stored per row.
        fb_rows = self.conn.execute(
            f"""SELECT uf.email_id as item_id, 'email' as item_type,
                      e.subject as title, uf.label as user_label,
                      uf.feedback_at as labeled_at, e.origin_url as url,
                      ? as label_source, NULL as label_reason
                      {extra_email_cols}
               FROM user_feedback uf
               JOIN emails e ON uf.email_id = e.id
               WHERE {email_label_filter}
               ORDER BY uf.feedback_at DESC LIMIT ?""",
            (USER_SOURCE, RECENT_PREDICTIONS_LIMIT),
        ).fetchall()
        for r in fb_rows:
            item = dict(r)
            item["safe_email_id"] = (
                item["item_id"] if EMAIL_ID_PATTERN.match(item["item_id"]) else ""
            )
            items.append(item)
        sj_rows = self.conn.execute(
            f"""SELECT CAST(id AS TEXT) as item_id, 'scraped_job' as item_type,
                      title, user_label, labeled_at, url, label_source, label_reason
               FROM scraped_jobs
               WHERE {scraped_label_filter}
               ORDER BY labeled_at DESC LIMIT ?""",
            (RECENT_PREDICTIONS_LIMIT,),
        ).fetchall()
        for r in sj_rows:
            items.append(dict(r))
        items.sort(key=lambda x: label_sort_key(x.get("labeled_at")), reverse=True)
        return items[:RECENT_PREDICTIONS_LIMIT]

    def _attach_predictions(
        self, items: list[dict], model_type: str | None = None,
    ) -> None:
        """Batch-fetch ML predictions for items, avoiding N+1 queries."""
        if not items:
            return
        placeholders = ", ".join(["(?, ?)"] * len(items))
        params: list[str] = []
        for item in items:
            params.extend([item["item_type"], item["item_id"]])
        if model_type:
            type_clause = " AND mv.model_type = ?"
            params.append(model_type)
        else:
            type_clause = ""
        rows = self.conn.execute(
            f"""SELECT p.item_type, p.item_id, mv.algorithm,
                       p.prediction, p.probability
                FROM ml_predictions p
                JOIN model_versions mv ON p.model_version_id = mv.id
                WHERE (p.item_type, p.item_id) IN ({placeholders})
                      {type_clause}""",
            params,
        ).fetchall()
        preds_by_item: dict[tuple[str, str], dict] = {}
        for r in rows:
            key = (r["item_type"], r["item_id"])
            preds_by_item.setdefault(key, {})[r["algorithm"]] = {
                "prediction": r["prediction"],
                "probability": r["probability"],
            }
        for item in items:
            key = (item["item_type"], item["item_id"])
            item["predictions"] = preds_by_item.get(key, {})
