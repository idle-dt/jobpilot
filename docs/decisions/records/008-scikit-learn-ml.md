# ADR-008: scikit-learn for ML models

**Status:** accepted
**Date:** 2026-05-07
**Tags:** ml, classification

## Context

The optional ML refinement layer (see [ADR-004](004-rule-based-plus-ml.md)) trains
on the user's accumulated feedback labels. The datasets are **small** (tens to low
hundreds of labeled examples), the features are a handful of numeric scores, and
everything must train and predict **locally and quickly** on a personal machine.
We need calibrated probabilities (to show confidence) and reproducible results, not
a deep-learning stack.

## Decision

Use **scikit-learn** for the ML models. The trainer (`classifier/ml_trainer.py`)
trains four algorithms per model type and selects the best by F1:

```python
ALGORITHMS = {
    "LR":  lambda: LogisticRegression(max_iter=1000, random_state=42, class_weight="balanced"),
    "RF":  lambda: RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced"),
    "GBC": lambda: CalibratedClassifierCV(GradientBoostingClassifier(n_estimators=100, random_state=42)),
    "SVM": lambda: CalibratedClassifierCV(LinearSVC(max_iter=2000, random_state=42, class_weight="balanced")),
}
```

- **`random_state=42`** everywhere for reproducibility.
- **`class_weight="balanced"`** to handle label imbalance.
- **Conservative hyperparameters** for small data (`n_estimators=100`, `max_iter=1000/2000`).
- `CalibratedClassifierCV` wraps SVM/GBC so they produce probability estimates.
- Evaluation via `StratifiedKFold` cross-validation (accuracy, precision, recall, F1);
  the best-F1 model is activated. Models are serialized with `joblib` and stored as
  blobs in the database alongside their metrics.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Deep learning (PyTorch/TensorFlow) | Massive overkill for tens of numeric features and tiny datasets; heavy install, slow, needs far more data. |
| Hand-rolled logistic regression | Reinventing well-tested estimators, CV, calibration, and metrics that scikit-learn provides. |
| Gradient-boosting libs (XGBoost/LightGBM) | Extra native dependencies for marginal benefit on small tabular data; scikit-learn's GBC suffices. |

## Consequences

### Positive
- Mature, well-documented estimators with built-in CV, metrics, and calibration.
- Trains and predicts fast on small local datasets.
- Seeded runs are reproducible; calibrated probabilities power confidence display.

### Negative / Tradeoffs
- scikit-learn + numpy/scipy are sizeable dependencies for a small tool.
- Model selection across four algorithms adds training time and code complexity.

### Risks
- Pickled/joblib model blobs are tied to library versions — a scikit-learn upgrade may invalidate stored models and require retraining.

## Related

- ADRs: [ADR-004](004-rule-based-plus-ml.md) (rules + optional ML design)
- Code: `src/jobpilot/classifier/ml_trainer.py`
- Docs: `CLAUDE.md` (Code Rules — ML: seed randomness, feature-name constants, document hyperparameters)
