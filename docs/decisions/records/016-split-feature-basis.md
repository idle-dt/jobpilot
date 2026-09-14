# ADR-016: Scoring features read user preferences; noise features stay hardcoded

**Status:** accepted
**Date:** 2026-09-14
**Tags:** ml, classification, storage

## Context

Both ML models are trained on the same six rule-based features produced by
`compute_features(subject, body, config)` in `classifier/rules.py`. That function takes an
optional `SignalConfig`; with none it falls back to the hardcoded tables in
`classifier/signals.py`. `MLTrainer` passed nothing, so every model scored against the
hardcoded tables while the rule-based scorer read the user's saved preferences via
`load_signal_config(repo)`.

That mattered once the search policy changed. `LOCATION_PATTERNS` ranks `netherlands` at 1.0
above `remote` at 0.9 — under a remote-only policy the feature itself encoded the abandoned
rule, and no amount of relabelling could correct it, because the input the model sees never
changed. Measured on a real listing: a genuinely remote role scored `location_match` 0.900
while an Amsterdam onsite role scored 1.000.

The obvious fix — pass the config everywhere — has a catch. The two models answer different
questions. `scoring` asks "is this worth checking, for me?"; `noise` asks "is this a job
posting at all?". Making noise features preference-aware would mean the active noise model
(RF, f1 0.989, trained on 738 labels) has its inputs redefined underneath it, and every
future preference edit would have to retire it — undoing the narrowing of
`_invalidate_if_scoring` that keeps the noise model serving through a preference change.

## Decision

The feature basis is chosen per model type, not globally.

- **Scoring** paths pass `MLTrainer.signal_config`, a `SignalConfig` built from the user's
  saved preferences and cached per trainer instance so one training or prediction run stays
  internally consistent. A new instance picks up preference edits.
- **Noise** paths call `compute_features(subject, body)` with no config and keep the
  hardcoded tables. Whether something is a job posting is a generic question; answering it
  with the user's location taste would be wrong in principle as well as destabilising.
- `LOCATION_PATTERNS` therefore has two distinct jobs: the noise fallback basis
  (`features.py:77`) and the signal-chip source (`signals.py:226`). Seeding a fresh database
  was a third, conflicting use — it is why a new install started on the abandoned NL/SE/NO
  policy. Seeding now reads a separate `DEFAULT_LOCATION_PREFERENCES`, leaving
  `LOCATION_PATTERNS` free to stay stable for the noise model.
- A one-time migration retires scoring models fitted to the old basis, so a version
  reactivated by hand from the experiment lab cannot silently serve against features that no
  longer mean what it learned.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Pass the config everywhere, including noise | Redefines the inputs of an active model with f1 0.989 and 738 labels, forcing a retrain; every later preference edit would have to retire the noise model too |
| Leave `MLTrainer` preference-blind, tune the hardcoded tables instead | Makes the app's own settings screen decorative for the ML path and re-splits the source of truth the moment preferences change again |
| Change `LOCATION_PATTERNS` itself to remote-only | Same table feeds noise features and the signal chips; narrowing it shifts the trained noise model's inputs — the exact outcome this split exists to prevent |
| Record the feature basis on `model_versions` and pick at load time | Only useful once models of different bases coexist; the one-time retirement prevents that, and the column would need maintaining forever |

## Consequences

### Positive
- Scoring follows the settings screen. Changing a location preference changes what the model
  sees, and `_invalidate_if_scoring` already retires scoring models on such an edit.
- The noise model is insulated: its features, its training data and its active version all
  survive preference changes and criteria resets.
- A fresh install starts on the current policy rather than an abandoned one.

### Negative / Tradeoffs
- The same function returns different things for the two model types. Anyone reading
  `compute_features` in isolation will not see why — hence this record and the comments at
  each call site in `ml_trainer.py`.
- Two location tables now exist. They are not duplicates (one seeds preferences, one is the
  generic fallback) but they will look like drift to a reader who does not know the split.
  `test_noise_fallback_location_table_is_unchanged` pins the distinction.
- Scoring features are only as good as the stored preferences. A thin preference set scores
  worse than the hardcoded defaults did.

### Risks
- A future change that "unifies" the two tables, or that passes the config on a noise path
  for consistency, would silently degrade the active noise model. No test fails on feature
  *drift* — only the table-content pin would catch the most obvious form.
- The per-instance config cache assumes callers build an `MLTrainer` per unit of work. A
  long-lived trainer would train and predict against preferences edited in between.

## Related

- ADRs: [ADR-004](004-rule-based-plus-ml.md), [ADR-008](008-scikit-learn-ml.md)
- Specs: `SPEC_preference_aware_ml_features.md`, `SPEC_scoring_criteria_reset.md` (both shipped and removed)
- Code: `src/jobpilot/classifier/ml_trainer.py`, `src/jobpilot/classifier/rules.py`,
  `src/jobpilot/classifier/signals.py`, `src/jobpilot/storage/database.py`,
  `src/jobpilot/storage/migrations.py`
