"""ML training pipeline — trains multiple algorithms for noise and scoring models."""

import io
import json
import logging

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.svm import LinearSVC

from jobpilot.classifier.rules import FEATURE_NAMES, compute_features
from jobpilot.config import settings
from jobpilot.storage.models import MLPrediction, ModelVersion
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

ALGORITHMS = {
    "LR": lambda: LogisticRegression(max_iter=1000, random_state=42),
    "RF": lambda: RandomForestClassifier(n_estimators=100, random_state=42),
    "GBC": lambda: GradientBoostingClassifier(n_estimators=100, random_state=42),
    "SVM": lambda: CalibratedClassifierCV(LinearSVC(max_iter=2000, random_state=42)),
}


class MLTrainer:
    """Trains and evaluates multiple ML algorithms."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def train_all(self, model_type: str) -> list[int]:
        """Train all 4 algorithms for a model type. Returns list of model_version IDs."""
        if model_type == "noise":
            data = self.repo.get_noise_training_data()
        else:
            data = self.repo.get_scoring_training_data()

        if len(data) < settings.min_training_samples:
            logger.info(
                "Not enough data for %s: %d < %d",
                model_type, len(data), settings.min_training_samples,
            )
            return []

        if model_type == "noise":
            neg_count = sum(1 for d in data if d["label"] == 0)
            if neg_count < 5:
                logger.info("Noise model needs 5+ not_a_job labels, has %d", neg_count)
                return []

        x_train = np.array([
            compute_features(d.get("subject") or "", d.get("body") or d.get("body_text") or "")
            for d in data
        ])
        y_train = np.array([d["label"] for d in data])

        version = self.repo.get_next_version(model_type)
        model_ids = []
        best_f1 = -1.0
        best_id = None

        for algo_name, algo_factory in ALGORITHMS.items():
            model_id = self._train_single(
                algo_name, algo_factory, x_train, y_train, model_type, version,
            )
            if model_id:
                model_ids.append(model_id)
                mv = self.repo.get_model_version(model_id)
                if mv and (mv.f1_score or 0) > best_f1:
                    best_f1 = mv.f1_score or 0
                    best_id = model_id

        if best_id:
            mv = self.repo.get_model_version(best_id)
            self.repo.activate_model_by_id(best_id, model_type)
            logger.info(
                "Activated %s model id=%d algo=%s (F1=%.3f)",
                model_type, best_id, mv.algorithm if mv else "?", best_f1,
            )

        self._predict_all(model_type, model_ids)
        return model_ids

    def _train_single(
        self, algo_name: str, algo_factory,
        x: np.ndarray, y: np.ndarray,
        model_type: str, version: int,
    ) -> int | None:
        """Train one algorithm, cross-validate, serialize, store."""
        try:
            clf = algo_factory()

            min_class = int(np.min(np.bincount(y)))
            n_splits = min(5, min_class)
            n_splits = max(2, n_splits)
            cv = StratifiedKFold(
                n_splits=n_splits, shuffle=True, random_state=42,
            )
            scores = cross_validate(
                clf, x, y, cv=cv,
                scoring=["accuracy", "precision", "recall", "f1"],
                return_train_score=False,
            )

            clf.fit(x, y)

            importances = self._extract_importances(clf, algo_name)

            buf = io.BytesIO()
            joblib.dump(clf, buf)
            model_blob = buf.getvalue()

            feature_data = json.dumps({
                "names": FEATURE_NAMES,
                "importances": importances,
            })

            mv = ModelVersion(
                id=None,
                version=version,
                training_samples=len(y),
                model_blob=model_blob,
                accuracy=float(np.mean(scores["test_accuracy"])),
                precision_score=float(np.mean(scores["test_precision"])),
                recall_score=float(np.mean(scores["test_recall"])),
                f1_score=float(np.mean(scores["test_f1"])),
                feature_names=feature_data,
                is_active=False,
                model_type=model_type,
                algorithm=algo_name,
            )
            model_id = self.repo.insert_model_version(mv)
            logger.info(
                "Trained %s/%s: F1=%.3f, samples=%d",
                model_type, algo_name, mv.f1_score, len(y),
            )
            return model_id

        except Exception:
            logger.exception("Failed to train %s/%s", model_type, algo_name)
            return None

    def _extract_importances(self, clf, algo_name: str) -> list[float]:
        """Extract feature importances from a trained classifier."""
        try:
            if hasattr(clf, "feature_importances_"):
                return clf.feature_importances_.tolist()
            if hasattr(clf, "coef_"):
                return np.abs(clf.coef_[0]).tolist()
            if hasattr(clf, "calibrated_classifiers_"):
                base = clf.calibrated_classifiers_[0].estimator
                if hasattr(base, "coef_"):
                    return np.abs(base.coef_[0]).tolist()
        except Exception:
            logger.debug("Could not extract importances for %s", algo_name)
        return [0.0] * len(FEATURE_NAMES)

    def _predict_all(self, model_type: str, model_ids: list[int]) -> None:
        """Run predictions for all trained models on relevant items."""
        for model_id in model_ids:
            mv = self.repo.get_model_version(model_id)
            if not mv:
                continue

            clf = joblib.load(io.BytesIO(mv.model_blob))
            self.repo.delete_predictions_for_model(model_id)
            predictions: list[MLPrediction] = []

            if model_type == "noise":
                rows = self.repo.conn.execute(
                    "SELECT id, subject, body_text FROM emails WHERE processed = TRUE"
                ).fetchall()
                for row in rows:
                    features = compute_features(row["subject"], row["body_text"] or "")
                    x_item = np.array([features])
                    prob = self._get_positive_prob(clf, x_item)
                    pred_label = "job" if prob >= 0.5 else "not_a_job"
                    predictions.append(MLPrediction(
                        id=None, model_version_id=model_id,
                        item_type="email", item_id=row["id"],
                        prediction=pred_label, probability=prob,
                    ))
            else:
                email_rows = self.repo.conn.execute(
                    "SELECT id, subject, body_text FROM emails WHERE processed = TRUE"
                ).fetchall()
                for row in email_rows:
                    features = compute_features(row["subject"], row["body_text"] or "")
                    x_item = np.array([features])
                    prob = self._get_positive_prob(clf, x_item)
                    pred_label = "worth_checking" if prob >= 0.5 else "skip"
                    predictions.append(MLPrediction(
                        id=None, model_version_id=model_id,
                        item_type="email", item_id=row["id"],
                        prediction=pred_label, probability=prob,
                    ))

                job_rows = self.repo.conn.execute(
                    "SELECT id, title, company, location, description FROM scraped_jobs"
                ).fetchall()
                for row in job_rows:
                    body = (
                        f"{row['title']} {row['company'] or ''}"
                        f" {row['location'] or ''} {row['description'] or ''}"
                    )
                    features = compute_features(row["title"], body)
                    x_item = np.array([features])
                    prob = self._get_positive_prob(clf, x_item)
                    pred_label = "worth_checking" if prob >= 0.5 else "skip"
                    predictions.append(MLPrediction(
                        id=None, model_version_id=model_id,
                        item_type="scraped_job", item_id=str(row["id"]),
                        prediction=pred_label, probability=prob,
                    ))

            if predictions:
                self.repo.insert_predictions(predictions)
                logger.info(
                    "Stored %d predictions for %s/%s",
                    len(predictions), model_type, mv.algorithm,
                )

    def predict_single(
        self, model_type: str, item_type: str, item_id: str,
        subject: str, body: str,
    ) -> dict[str, dict]:
        """Run all models of a type on a single item.

        Returns {algo: {prediction, probability, is_active}}.
        """
        models = self.repo.get_model_versions_by_type(model_type)
        if not models:
            return {}

        features = compute_features(subject, body)
        x_item = np.array([features])
        results: dict[str, dict] = {}
        predictions_to_store: list[MLPrediction] = []

        for mv in models:
            clf = joblib.load(io.BytesIO(mv.model_blob))
            prob = self._get_positive_prob(clf, x_item)

            if model_type == "noise":
                pred_label = "job" if prob >= 0.5 else "not_a_job"
            else:
                pred_label = "worth_checking" if prob >= 0.5 else "skip"

            results[mv.algorithm] = {
                "prediction": pred_label,
                "probability": prob,
                "is_active": mv.is_active,
            }
            predictions_to_store.append(MLPrediction(
                id=None, model_version_id=mv.id,
                item_type=item_type, item_id=item_id,
                prediction=pred_label, probability=prob,
            ))

        if predictions_to_store:
            self.repo.insert_predictions(predictions_to_store)

        return results

    def should_retrain(self, model_type: str) -> bool:
        """Check if conditions are met for automatic retraining."""
        if model_type == "noise":
            data = self.repo.get_noise_training_data()
            if len(data) < settings.min_training_samples:
                return False
            neg_count = sum(1 for d in data if d["label"] == 0)
            if neg_count < 5:
                return False
        else:
            data = self.repo.get_scoring_training_data()
            if len(data) < settings.min_training_samples:
                return False

        last_train = self.repo.get_last_training_time(model_type)
        new_labels = self.repo.count_labels_since(last_train)
        return new_labels >= settings.retrain_after_n_labels

    @staticmethod
    def _get_positive_prob(clf, x: np.ndarray) -> float:
        """Get probability for the positive class (index 1)."""
        if hasattr(clf, "predict_proba"):
            proba = clf.predict_proba(x)[0]
            return float(proba[1]) if len(proba) > 1 else float(proba[0])
        pred = clf.predict(x)[0]
        return 1.0 if pred == 1 else 0.0
