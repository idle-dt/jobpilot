# ADR-004: Rule-based scoring + optional ML

**Status:** accepted
**Date:** 2026-05-07
**Tags:** ml, classification

## Context

JobPilot must decide which incoming job listings are "worth checking" vs "skip".
At install time there is **no training data** — the user has labeled nothing yet,
so a purely ML-based classifier would have nothing to learn from and would be
useless on day one. At the same time, we want the system to improve as the user
gives feedback. The classifier therefore needs to work immediately with zero
labels and get better over time.

## Decision

Use a **deterministic rule-based scorer as the always-on baseline**, with ML as
an **optional refinement layer** that activates only once enough labeled data
exists.

- **Rule-based path** (`classifier/rules.py`): `compute_features()` produces six
  named feature scores (`tech_match`, `job_title`, `location_match`,
  `seniority_match`, `salary_match`, `negative_signals`) from user-configured
  keyword signals. `RuleBasedScorer.score()` applies configurable weights, blends
  job-title into tech match, and classifies against a threshold with a confidence
  value. Negation-aware processing suppresses positive keywords inside negation
  phrases.
- **ML path** (`classifier/ml_trainer.py`, see [ADR-008](008-scikit-learn-ml.md)):
  training is gated on `settings.min_training_samples` (and extra minimums for the
  noise model). Below the threshold, training is a no-op and the rule scores stand
  alone. Above it, models are trained and their predictions are shown alongside the
  rule output for comparison.

Rules always run; ML never replaces them — it augments and is compared against them.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Pure ML classifier | No labeled data at install time; cold-start makes it unusable until the user has labeled many items. |
| Pure rule-based, no ML | Cannot adapt to the user's individual taste beyond the keyword config; plateaus. |
| LLM-based classification per email | Cost, latency, and sends content to an external service — conflicts with the local-first design. |

## Consequences

### Positive
- Works immediately with zero training data via transparent, explainable rules.
- Improves with user feedback once enough labels accumulate.
- Rule scores remain a stable, debuggable baseline to compare ML against.

### Negative / Tradeoffs
- Two scoring paths to maintain and keep feature-compatible.
- Rule weights and keyword signals require manual tuning.

### Risks
- Feature definitions must stay consistent between the rule scorer and the ML feature vectors, or trained models mispredict.

## Related

- ADRs: [ADR-008](008-scikit-learn-ml.md) (scikit-learn models for the ML layer)
- Code: `src/jobpilot/classifier/rules.py`, `signals.py`, `features.py`, `ml_trainer.py`
- Docs: `CLAUDE.md` (Architecture — classifier pipeline)

> Note: the "rules first, ML optional" framing is the de facto design read from the
> code (training gated on `min_training_samples`; rules always executed). It was not
> written down as an explicit decision at the time.
