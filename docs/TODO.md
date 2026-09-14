# JobPilot — Master TODO

Roadmap, task tracking, bugs, and feature ideas for the JobPilot project.
This is the single source of truth for what needs to be done — check and update regularly.

## Bugs

### `count_labels_since` compares timestamps as raw strings

`ml_repo.py:282` compares `user_feedback.feedback_at` (`YYYY-MM-DD HH:MM:SS`) and
`scraped_jobs.labeled_at` (ISO-8601 with `T`) against a cutoff using `>` on the raw text.
Because `' ' < 'T'`, a scraped-job label always sorts after a same-second feedback label,
so `should_retrain` over-counts new labels and retrains slightly early. Wrap both sides in
`datetime()` as `SPEC_scoring_criteria_reset.md` does for its own cutoff.

## In Progress

### `docs/specs/SPEC_scoring_criteria_reset.md` — Scoring Criteria Reset

Adds a criteria cutoff so scoring labels given under the old "remote or relocation to
NL/SE/NO" policy stop training the model after the switch to remote-only. Retires active
scoring models, leaves the noise model and every label row untouched.

### `docs/specs/SPEC_preference_aware_ml_features.md` — Preference-Aware Scoring Features

`MLTrainer` computes features with no `SignalConfig`, so scoring models score locations
against the hardcoded `LOCATION_PATTERNS` instead of the user's saved preferences. Passes
the config through on the scoring paths only, retires the preference-blind models once, and
stops `hybrid` inheriting the `remote` weight. Noise features stay generic by design.

## Tech Debt

### 20 functions exceed the CLAUDE.md 30-line limit

`scripts/check_function_length.py` enforces the rule on changed files via the pre-commit
hook (as a warning). Enabling ruff's `PLR0915` repo-wide would flag 20 pre-existing
functions at `max-statements=20`, and 4 even at 30 — worst offenders are
`ml_trainer.py:84` (48 statements), `arbeitnow.py:42` (41) and `features.py:224` (36).
Clean these up before making the check a blocker.

### The pre-commit hook is not shared

`.git/hooks/pre-commit` is untracked, so lint/length/test checks only run for clones that
set it up by hand. Moving it to a tracked directory with `git config core.hooksPath` would
give every clone the same gate.

### Application status vocabulary is duplicated across 4 places — guarded

The valid-status set is still declared in four places (`APPLICATION_STATUSES`,
`STATUS_SORT_RANK`, `STATUS_LABELS` in `services/tracker_service.py`, and the two SQL
`CHECK(status IN (...))` lists in `storage/database.py`), but they can no longer
*silently* drift: `test_status_*` parity guards in `tests/test_storage.py` fail the build
if any copy diverges from the canonical tuple. This kills the latent bug where a status
missing from `STATUS_SORT_RANK` would silently sort to the bottom of the tracker.

The duplication itself remains by deliberate choice — statuses are a fixed,
developer-controlled vocabulary, and a derived single source of truth (an
`ApplicationStatus` enum/registry feeding the tuple, maps, and a generated SQL CHECK) was
judged not worth the cost: it would require building SQL via string interpolation, against
the no-f-string-SQL rule, while `STATUS_SORT_RANK` would still need a hand-authored map and
guard. Revisit that fuller refactor only if the status set starts changing frequently.

### `storage/ml_repo.py` is over the 300-line limit

`ml_repo.py` was already 346 lines before the criteria-reset work and is now 391. The
cohesive split is to move the Training Data section (`get_noise_training_data`,
`get_scoring_training_data` and its two row helpers, `get_last_training_time`,
`count_labels_since`, `get_recent_predictions_comparison`) into a `training_data_repo.py`
composed by `MLRepository`, which would put both files well under the limit. Deferred to
keep the criteria-reset branch focused on behaviour. `repository.py` (367 lines) is over
for the same structural reason — it is a pure delegation facade.

### `classifier/ml_trainer.py` still over the 300-line limit

`ml_trainer.py` is ~476 lines. The worst long functions were broken into helpers
(`_train_single` → `_cross_validate` + `_build_model_version`; `_predict_all` →
`_predict_noise` + `_predict_scoring`), but the file as a whole is still over the limit.
A further split — e.g. moving the prediction surface (`_predict_*`, `predict_single`) into
a separate `ml_predictor` module from training — would bring it under 300. Deferred to
avoid churn in the ML path; lower priority than behaviour-changing work.

### Remaining test coverage gaps

Tests now cover the storage layer, parsers, digests, the scraper, the extracted services
(`InboxService`, `MLExportService`, `SettingsService`), and key route handlers (inbox,
settings, ML export). Still untested:

- Remaining services (`classification_service.py`, `sync_service.py`, `ml_service.py`, `tracker_service.py`)
- ML pipeline (`ml_trainer.py` training/prediction, `ml_prediction.py`)
- Repositories (`app_repo.py`, `email_repo.py`, `ml_repo.py`, `predictions_repo.py`) beyond storage basics

## UI Improvements

- Description block expand/collapse animation (smooth slide-in/slide-out)

## Planned Features

### Classification
- ~~Salary threshold scoring~~ — shipped
- ~~Negation-aware signal matching~~ — shipped

### Expired Job Auto-Detection
- Auto-detect expired jobs via URL scraping (404/redirect) or date heuristic
- Title mismatch detection on re-scrape — if the scraped title no longer matches the stored title, the listing was recycled/reposted
- Manual toggle already implemented

### Deployment & Hosting
- Dockerize the app (Dockerfile, docker-compose)
- Add production WSGI server (gunicorn)
- CI/CD pipeline for automated testing and deployment
- Environment-based configuration (dev / staging / production)
