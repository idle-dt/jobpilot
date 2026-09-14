# ADR-017: Machine-authored labels share the label column, tagged by provenance

**Status:** accepted
**Date:** 2026-09-14
**Tags:** ml, classification, storage, process

## Context

The scraped-job review queue held 477 unlabeled jobs and grew with every sync —
more than anyone clears by hand. At the same time the scoring model had almost
nothing to learn from: the criteria reset excluded every earlier label, leaving
`get_scoring_training_data()` returning 2 rows.

Labeling the queue in bulk solves the chore and is the only realistic way to refill
the training set. But it inverts the ratio: machine-authored labels would become
nearly all of the training data. Written into `scraped_jobs.user_label` with no way
to tell them apart, the model would be fitted to an unaudited imitation of the
user's criteria, and there would be no way to undo it short of hand-inspecting
every row.

The question was not whether to label in bulk, but what has to be true for the
result to be safe to keep.

## Decision

Bulk labels go in the same `user_label` column as hand-clicked ones, and carry
their provenance alongside:

- **`scraped_jobs.label_source`** — `'user'` for a click in the UI, `'assistant'`
  for a `label-batch` run, NULL while unlabeled. The migration backfills `'user'`
  for every pre-existing label.
- **`scraped_jobs.label_reason`** — the rationale the run stated, shown in the UI
  and in the generated review document. A hand click leaves it NULL; a click has no
  stated reason.

Four properties make this safe:

1. **Reversible.** `label-revert --source assistant` clears exactly the rows one
   author wrote. Hand-clicked labels are untouched.
2. **Gated.** `training_includes_assistant_labels` defaults to **off**.
   `_scoring_rows_from_jobs` excludes assistant rows unless it is on, so the label
   count on the settings page stays honest about what actually trains the model.
3. **Audited.** Every run — preview included — writes a JSONL log with one line per
   input entry and its outcome, plus a grouped Markdown review document.
4. **Refusable.** A confidence floor (default 0.95) rejects low-confidence
   judgements rather than writing them. A rejection changes nothing; the job stays
   in the queue.

The criteria themselves live in `docs/labeling-criteria.md`, versioned in git, not
in a prompt — so a run is reproducible and a disagreement is fixed by editing one
document.

**`label_source = 'assistant'` is not an ML prediction.** Model predictions live in
`ml_predictions` and are untouched by this feature. The word describes who authored
a label, never how correct it is.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| A separate `assistant_labels` table | Every read of a label — the review queue, the stats page, `count_labels_since`, training data — would need a UNION or a second query. The provenance question is one column wide; a table is the wrong shape for it, and the duplication would drift. |
| Write bulk labels indistinguishably into `user_label` | The failure this whole design exists to prevent. No way to revert, audit, or hold them out of training. |
| Don't label in bulk; clear the queue by hand | The queue grows faster than it is cleared, and the training set stays at 2 rows indefinitely. |
| Let the rule scorer auto-label below a score threshold | Cements the scorer's own judgments as training truth — the model would learn to reproduce the rules it is supposed to improve on. Explicitly out of scope. |
| Gate on the queue or the UI instead of on training | The labels are useful in the queue immediately; the risk is confined to training. Gating the visible parts would cost the benefit without removing the risk. |

## Consequences

### Positive

- The queue shrinks without the training set silently absorbing machine judgement.
- Provenance is one indexed column, so every existing query keeps working.
- A run is undoable in one command, which makes trying a set of criteria cheap.
- The audit trail made a bad run detectable: the first real run inferred `skip`
  from a city name with no remote wording, 13 of 19 Android skips failed the
  spot-check, and the whole run was reverted and re-done under corrected criteria.

### Negative / Tradeoffs

- Two sources of truth for "who labeled this" must stay in sync: the UI path
  (`update_scraped_job_label`, defaulting to `'user'`) and the bulk path.
- The training gate means the settings page reports a label count lower than the
  number of labels that exist. That is intentional and the copy says so, but it
  reads as a bug until explained.
- `--force` transfers ownership: a hand-clicked label overwritten by a forced run
  becomes an assistant label, and a later revert clears it rather than restoring
  the click. Nothing records the prior value.

### Risks

- **The gate is one boolean away from being pointless.** If the setting is turned
  on before a spot-check, the unaudited-imitation failure happens anyway. The
  workflow requires a 30-label sample at ~95% agreement before flipping it, but
  nothing in the code enforces that.
- **The noise model still trains on assistant labels.** `get_noise_training_data`
  asks "is this row a job posting", which a bulk-labeled row is regardless of
  author, so this is believed correct — but it is an exception to the gate and
  should be revisited if the noise model starts using the label value.

## Related

- ADRs: [ADR-004](004-rule-based-plus-ml.md) (rule-based scoring plus optional ML),
  [ADR-016](016-split-feature-basis.md) — this change extends the same split to
  negative signals: `WORKPLACE_NEGATIVE_SIGNALS` seeds user preferences but is kept
  out of `NEGATIVE_SIGNALS`, the hardcoded basis the noise model scores against.
- Code: `src/jobpilot/storage/label_repo.py`,
  `src/jobpilot/services/label_service.py`,
  `src/jobpilot/services/label_report.py`,
  `src/jobpilot/storage/ml_repo.py` (`_assistant_author_filter`),
  `docs/labeling-criteria.md`, `.claude/commands/label-queue.md`
