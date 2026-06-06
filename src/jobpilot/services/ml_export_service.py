"""Business logic for exporting ML model data as JSON."""

import json
import logging
from datetime import datetime

from jobpilot.classifier.rules import FEATURE_NAMES, compute_features
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

# How many recent labeled predictions to include in the export comparison.
EXPORT_PREDICTIONS_LIMIT = 50
# Model types the export endpoint accepts.
VALID_MODEL_TYPES = ("noise", "scoring")


class MLExportService:
    """Assembles the JSON export of training data, model metrics, and predictions."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def build_export(self, model_type: str) -> dict:
        """Build the full export dict for the given model type."""
        models = self.repo.get_model_versions_by_type(model_type)
        return {
            "exported_at": datetime.now().isoformat(),
            "model_type": model_type,
            "training_data": {
                "feature_names": FEATURE_NAMES,
                "samples": self._build_samples(model_type),
            },
            "algorithms": self._build_algorithms(models),
            **self._build_predictions(),
        }

    def _build_samples(self, model_type: str) -> list[dict]:
        """Compute feature vectors for every labeled training sample."""
        if model_type == "noise":
            raw_data = self.repo.get_noise_training_data()
        else:
            raw_data = self.repo.get_scoring_training_data()
        samples = []
        for d in raw_data:
            subject = d.get("subject") or ""
            body = d.get("body") or d.get("body_text") or ""
            samples.append({
                "item_type": d.get("item_type", "email"),
                "item_id": d.get("item_id") or d.get("email_id") or "",
                "title": subject,
                "features": compute_features(subject, body),
                "user_label": d.get("label"),
            })
        return samples

    @classmethod
    def _build_algorithms(cls, models: list) -> dict:
        """Build the per-algorithm metrics and feature-importance map."""
        algorithms = {}
        for mv in models:
            algorithms[mv.algorithm] = {
                "metrics": {
                    "accuracy": mv.accuracy,
                    "precision": mv.precision_score,
                    "recall": mv.recall_score,
                    "f1": mv.f1_score,
                },
                "feature_importances": cls._importance_dict(mv.feature_names),
                "is_active": mv.is_active,
            }
        return algorithms

    @staticmethod
    def _importance_dict(feature_names: str | None) -> dict:
        """Decode stored feature_names JSON into a {name: importance} map."""
        feat_data = {}
        if feature_names:
            try:
                feat_data = json.loads(feature_names)
            except (json.JSONDecodeError, TypeError):
                pass
        importances = feat_data.get("importances", [])
        return {
            name: round(importances[i], 4)
            for i, name in enumerate(FEATURE_NAMES)
            if i < len(importances)
        }

    def _build_predictions(self) -> dict:
        """Build the predictions list and the subset where models disagree with labels."""
        comparison = self.repo.get_recent_predictions_comparison(
            limit=EXPORT_PREDICTIONS_LIMIT
        )
        predictions = []
        disagreements = []
        for item in comparison:
            pred_entry, disagree_algos = self._build_prediction_entry(item)
            predictions.append(pred_entry)
            if disagree_algos:
                disagreements.append({
                    "item_id": item["item_id"],
                    "title": item.get("title", ""),
                    "user_label": item.get("user_label", ""),
                    "models_that_disagree": disagree_algos,
                })
        return {"predictions": predictions, "disagreements": disagreements}

    @staticmethod
    def _build_prediction_entry(item: dict) -> tuple[dict, list[str]]:
        """Build one prediction entry and the list of algorithms disagreeing with the label."""
        pred_entry = {
            "item_type": item["item_type"],
            "item_id": item["item_id"],
            "title": item.get("title", ""),
            "user_label": item.get("user_label", ""),
            "rule_score": item.get("raw_score"),
            "ml_predictions": {},
        }
        disagree_algos = []
        for algo, pdata in item.get("predictions", {}).items():
            pred_entry["ml_predictions"][algo] = {
                "prediction": pdata["prediction"],
                "probability": pdata["probability"],
            }
            if pdata["prediction"] != item.get("user_label"):
                disagree_algos.append(algo)
        return pred_entry, disagree_algos
