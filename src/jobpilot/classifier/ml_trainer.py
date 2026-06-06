"""ML training pipeline — trains multiple algorithms for noise and scoring models."""

import io
import json
import logging

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, make_scorer, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.svm import LinearSVC

from jobpilot.classifier.rules import FEATURE_NAMES, compute_features
from jobpilot.classifier.structural_features import (
    STRUCTURAL_FEATURE_NAMES_TIER1,
    STRUCTURAL_FEATURE_NAMES_TIER2,
    compute_structural_features,
)
from jobpilot.config import settings
from jobpilot.storage.models import MLPrediction, ModelVersion
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

# Conservative defaults for small datasets (<200 samples):
# - n_estimators=100: enough trees without overfitting on small data
# - max_iter=1000/2000: ensure convergence on small datasets
# - random_state=42: reproducible results across runs
ALGORITHMS = {
    "LR": lambda: LogisticRegression(
        max_iter=1000, random_state=42, class_weight="balanced",
    ),
    "RF": lambda: RandomForestClassifier(
        n_estimators=100, random_state=42, class_weight="balanced",
    ),
    # GBC: no class_weight support; boosting partially mitigates imbalance
    "GBC": lambda: CalibratedClassifierCV(
        GradientBoostingClassifier(n_estimators=100, random_state=42),
    ),
    "SVM": lambda: CalibratedClassifierCV(
        LinearSVC(max_iter=2000, random_state=42, class_weight="balanced"),
    ),
}

# Progressive feature tiers for the noise model only.
# Each tier adds structural features on top of the base 6.
NOISE_TIER1_MIN_LABELS = 30
NOISE_TIER2_MIN_LABELS = 60
MIN_NEGATIVE_LABELS = 5

NOISE_FEATURE_TIERS: dict[int, list[str]] = {
    0: [],
    1: STRUCTURAL_FEATURE_NAMES_TIER1,
    2: STRUCTURAL_FEATURE_NAMES_TIER1 + STRUCTURAL_FEATURE_NAMES_TIER2,
}

MAX_CV_SPLITS = 5
MIN_CV_SPLITS = 2


def get_noise_feature_tier(label_count: int) -> int:
    """Determine the feature tier based on noise label count."""
    if label_count >= NOISE_TIER2_MIN_LABELS:
        return 2
    if label_count >= NOISE_TIER1_MIN_LABELS:
        return 1
    return 0


def get_noise_feature_names(tier: int) -> list[str]:
    """Get the full ordered feature name list for a noise model at a given tier."""
    return FEATURE_NAMES + NOISE_FEATURE_TIERS[tier]


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
            if neg_count < MIN_NEGATIVE_LABELS:
                logger.info(
                    "Noise model needs %d+ not_a_job labels, has %d",
                    MIN_NEGATIVE_LABELS, neg_count,
                )
                return []

            tier = get_noise_feature_tier(len(data))
            feature_names_for_model = get_noise_feature_names(tier)
            extra_feature_names = NOISE_FEATURE_TIERS[tier]

            x_rows = []
            for d in data:
                subject = d.get("subject") or ""
                body = d.get("body") or d.get("body_text") or ""
                base = compute_features(subject, body)

                if extra_feature_names:
                    digest_count = 0
                    if d.get("item_source") == "email":
                        digest_count = self.repo.count_scraped_jobs_for_email(
                            d["email_id"]
                        )
                    structural = compute_structural_features(subject, body, digest_count)
                    base.extend(structural[name] for name in extra_feature_names)

                x_rows.append(base)

            x_train = np.array(x_rows)
        else:
            feature_names_for_model = FEATURE_NAMES
            x_train = np.array([
                compute_features(
                    d.get("subject") or "",
                    d.get("body") or d.get("body_text") or "",
                )
                for d in data
            ])

        y_train = np.array([d["label"] for d in data])

        version = self.repo.get_next_version(model_type)
        model_ids = []
        best_f1 = -1.0
        best_id = None

        for algo_name, algo_factory in ALGORITHMS.items():
            model_id = self._train_single(
                algo_name, algo_factory, x_train, y_train,
                model_type, version, feature_names_for_model,
            )
            if model_id:
                model_ids.append(model_id)
                mv = self.repo.get_model_version(model_id)
                if mv and (mv.f1_score or 0) > best_f1:
                    best_f1 = mv.f1_score or 0
                    best_id = model_id

        if not model_ids:
            return []

        # Delete old models only after new ones are saved — prevents data loss
        # if the subprocess is killed mid-training (daemon process or timeout).
        self.repo.delete_old_model_versions(model_type, keep_ids=model_ids)

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
        feature_names_for_model: list[str] | None = None,
    ) -> int | None:
        """Train one algorithm, cross-validate, serialize, store."""
        try:
            clf = algo_factory()
            scores = self._cross_validate(clf, x, y, algo_name)
            if scores is None:
                return None
            clf.fit(x, y)
            train_accuracy = float(clf.score(x, y))
            mv = self._build_model_version(
                clf, algo_name, y, model_type, version,
                scores, train_accuracy, feature_names_for_model,
            )
            model_id = self.repo.insert_model_version(mv)
            logger.info(
                "Trained %s/%s: F1=%.3f, samples=%d",
                model_type, algo_name, mv.f1_score, len(y),
            )
            return model_id
        except (ValueError, np.linalg.LinAlgError, RuntimeError):
            logger.exception("Failed to train %s/%s", model_type, algo_name)
            return None

    def _cross_validate(self, clf, x: np.ndarray, y: np.ndarray, algo_name: str) -> dict | None:
        """Cross-validate clf, returning score arrays, or None if too few samples."""
        # Defense-in-depth: should_retrain() checks MIN_NEGATIVE_LABELS for
        # noise, but scoring model and direct train_all() calls need this guard.
        min_class = int(np.min(np.bincount(y)))
        if min_class < MIN_CV_SPLITS:
            logger.warning(
                "Skipping %s — min class count %d < %d required",
                algo_name, min_class, MIN_CV_SPLITS,
            )
            return None
        n_splits = max(MIN_CV_SPLITS, min(MAX_CV_SPLITS, min_class))
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        scoring = {
            "accuracy": "accuracy",
            "precision": make_scorer(precision_score, zero_division=0),
            "recall": make_scorer(recall_score, zero_division=0),
            "f1": make_scorer(f1_score, zero_division=0),
        }
        return cross_validate(
            clf, x, y, cv=cv, scoring=scoring, return_train_score=False,
        )

    def _build_model_version(
        self, clf, algo_name: str, y: np.ndarray,
        model_type: str, version: int, scores: dict, train_accuracy: float,
        feature_names_for_model: list[str] | None,
    ) -> ModelVersion:
        """Build a ModelVersion from a fitted classifier and its CV scores."""
        names = feature_names_for_model or FEATURE_NAMES
        importances = self._extract_importances(clf, algo_name, len(names))
        buf = io.BytesIO()
        joblib.dump(clf, buf)
        feature_data = json.dumps({"names": names, "importances": importances})
        return ModelVersion(
            id=None,
            version=version,
            training_samples=len(y),
            model_blob=buf.getvalue(),
            accuracy=float(np.mean(scores["test_accuracy"])),
            precision_score=float(np.mean(scores["test_precision"])),
            recall_score=float(np.mean(scores["test_recall"])),
            f1_score=float(np.mean(scores["test_f1"])),
            feature_names=feature_data,
            is_active=False,
            model_type=model_type,
            algorithm=algo_name,
            train_accuracy=train_accuracy,
        )

    def _extract_importances(
        self, clf, algo_name: str, n_features: int | None = None,
    ) -> list[float]:
        """Extract feature importances from a trained classifier."""
        n = n_features or len(FEATURE_NAMES)
        try:
            if hasattr(clf, "feature_importances_"):
                return clf.feature_importances_.tolist()
            if hasattr(clf, "coef_"):
                return np.abs(clf.coef_[0]).tolist()
            if hasattr(clf, "calibrated_classifiers_"):
                base = clf.calibrated_classifiers_[0].estimator
                if hasattr(base, "feature_importances_"):
                    return base.feature_importances_.tolist()
                if hasattr(base, "coef_"):
                    return np.abs(base.coef_[0]).tolist()
        except (AttributeError, IndexError, ValueError):
            logger.debug("Could not extract importances for %s", algo_name)
        return [0.0] * n

    def _get_model_extra_features(self, mv: ModelVersion) -> list[str]:
        """Get the structural feature names a model was trained with (beyond base 6)."""
        if not mv.feature_names:
            return []
        try:
            stored_names = json.loads(mv.feature_names)["names"]
            return [n for n in stored_names if n not in FEATURE_NAMES]
        except (json.JSONDecodeError, KeyError):
            return []

    def _compute_noise_features(
        self, subject: str, body: str, extra_features: list[str],
        email_id=None,
    ) -> list[float]:
        """Compute full feature vector for noise model prediction."""
        features = compute_features(subject, body)
        if extra_features:
            digest_count = 0
            if email_id is not None:
                digest_count = self.repo.count_scraped_jobs_for_email(email_id)
            structural = compute_structural_features(subject, body, digest_count)
            features.extend(structural[name] for name in extra_features)
        return features

    def _predict_items(
        self, clf, model_id: int, items: list[dict],
        feature_fn, positive_label: str, negative_label: str,
        item_type: str,
    ) -> list[MLPrediction]:
        """Run a model against items and return predictions."""
        predictions: list[MLPrediction] = []
        for row in items:
            features = feature_fn(row)
            x_item = np.array([features])
            prob = self._get_positive_prob(clf, x_item)
            pred_label = positive_label if prob >= 0.5 else negative_label
            predictions.append(MLPrediction(
                id=None, model_version_id=model_id,
                item_type=item_type, item_id=str(row["id"]),
                prediction=pred_label, probability=prob,
            ))
        return predictions

    def _predict_all(self, model_type: str, model_ids: list[int]) -> None:
        """Run predictions for all trained models on relevant items."""
        for model_id in model_ids:
            mv = self.repo.get_model_version(model_id)
            if not mv:
                continue

            clf = joblib.load(io.BytesIO(mv.model_blob))
            self.repo.delete_predictions_for_model(model_id)
            if model_type == "noise":
                extra_features = self._get_model_extra_features(mv)
                predictions = self._predict_noise(clf, model_id, extra_features)
            else:
                predictions = self._predict_scoring(clf, model_id)

            if predictions:
                self.repo.insert_predictions(predictions)
                logger.info(
                    "Stored %d predictions for %s/%s",
                    len(predictions), model_type, mv.algorithm,
                )

    def _predict_noise(
        self, clf, model_id: int, extra_features: list[str],
    ) -> list[MLPrediction]:
        """Predict the noise model over all processed emails."""
        rows = self.repo.get_all_processed_emails()

        def noise_feature_fn(row: dict) -> list[float]:
            return self._compute_noise_features(
                row["subject"], row["body_text"] or "",
                extra_features, email_id=row["id"],
            )

        return self._predict_items(
            clf, model_id, rows, noise_feature_fn, "job", "not_a_job", "email",
        )

    def _predict_scoring(self, clf, model_id: int) -> list[MLPrediction]:
        """Predict the scoring model over all processed emails and scraped jobs."""
        email_rows = self.repo.get_all_processed_emails()

        def scoring_email_fn(row: dict) -> list[float]:
            return compute_features(row["subject"], row["body_text"] or "")

        predictions = self._predict_items(
            clf, model_id, email_rows, scoring_email_fn,
            "worth_checking", "skip", "email",
        )

        job_rows = self.repo.get_all_scraped_jobs()

        def scoring_job_fn(row: dict) -> list[float]:
            body = (
                f"{row['title']} {row['company'] or ''}"
                f" {row['location'] or ''} {row['description'] or ''}"
            )
            return compute_features(row["title"], body)

        predictions.extend(self._predict_items(
            clf, model_id, job_rows, scoring_job_fn,
            "worth_checking", "skip", "scraped_job",
        ))
        return predictions

    def predict_single(
        self, model_type: str, item_type: str, item_id: str,
        subject: str, body: str,
        digest_job_count: int = 0,
    ) -> dict[str, dict]:
        """Run all models of a type on a single item.

        Returns {algo: {prediction, probability, is_active}}.
        """
        models = self.repo.get_model_versions_by_type(model_type)
        if not models:
            return {}

        results: dict[str, dict] = {}
        predictions_to_store: list[MLPrediction] = []

        for mv in models:
            extra_features = self._get_model_extra_features(mv)

            if model_type == "noise" and extra_features:
                structural = compute_structural_features(
                    subject, body, digest_job_count,
                )
                features = compute_features(subject, body)
                features.extend(structural[name] for name in extra_features)
            else:
                features = compute_features(subject, body)

            x_item = np.array([features])
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
            if neg_count < MIN_NEGATIVE_LABELS:
                return False

            # Detect tier transition — force retrain if features should expand
            current_tier = get_noise_feature_tier(len(data))
            active_model = self.repo.get_active_model("noise")
            if active_model and active_model.feature_names:
                try:
                    stored_names = json.loads(active_model.feature_names)["names"]
                    expected_names = get_noise_feature_names(current_tier)
                    if len(stored_names) != len(expected_names):
                        logger.info(
                            "Noise tier transition: %d -> %d features",
                            len(stored_names), len(expected_names),
                        )
                        return True
                except (json.JSONDecodeError, KeyError):
                    pass
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
