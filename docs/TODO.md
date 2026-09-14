# JobPilot — Master TODO

Roadmap, task tracking, bugs, and feature ideas for the JobPilot project.
This is the single source of truth for what needs to be done — check and update regularly.

## Bugs

### `scraped_jobs.remote` is only ever set by the arbeitnow scraper

`arbeitnow.py:96` is the only line that sets `remote=True`. The LinkedIn, Glassdoor and
Wellfound digest paths never touch it, so it defaults `False`: 4 of 4 arbeitnow rows are
flagged against 0 of 2,357 from every other source, while **396 rows have "remote" in their
location text with `remote=0`**. Scoring is unaffected — it matches location *text* via
`geo.REMOTE_SYNONYMS` and `signals.LOCATION_PATTERNS`, not this boolean. The damage is at
`tracker_service.py:199`, which copies the flag onto tracked applications, so remote roles
show as on-site in the tracker. Fix means deciding whether `remote` is derived from location
text at insert or dropped in favour of the text.

### `count_labels_since` compares timestamps as raw strings

`ml_repo.py:282` compares `user_feedback.feedback_at` (`YYYY-MM-DD HH:MM:SS`) and
`scraped_jobs.labeled_at` (ISO-8601 with `T`) against a cutoff using `>` on the raw text.
Because `' ' < 'T'`, a scraped-job label always sorts after a same-second feedback label,
so `should_retrain` over-counts new labels and retrains slightly early. Wrap both sides in
`datetime()` as `SPEC_scoring_criteria_reset.md` does for its own cutoff.

### Trend chart cutoff compares local time against UTC

`stats_repo.py:241` builds `trend_cutoff` from `datetime.now()` (naive local) and compares it
against `scraped_at`, which is `CURRENT_TIMESTAMP` (UTC), without wrapping either side in
`datetime()`. Same bug class as the `labeled_at` stamp fixed in `job_repo.py`: the 30-day
trend window boundary is off by the machine's UTC offset. Cosmetic — it only shifts which
jobs fall in the first and last bucket of the chart. Fix by computing the cutoff in SQL as
`datetime('now', '-30 days')`.

### Bulk labeling leaves most of the queue undecided by design

The corrected `docs/labeling-criteria.md` treats a posting that never states its work mode
as unlabeled rather than `skip`. On the first 50 jobs that left 20 undecided — mostly
Swedish and Dutch Android roles whose descriptions simply never mention remote. They are
correct outcomes, not gaps, but it means a bulk run clears far less of the queue than its
size suggests. Revisit only if a later sample shows the postings do state work mode
somewhere the two-pass read is missing.

### Recent-labels lists sort three timestamp formats as raw strings

**Fixed** by `predictions_repo.label_sort_key`, which normalises the separator before
sorting. The note below is kept because the same latent issue remains in
`count_labels_since`.

`predictions_repo.py:78` and `ml_repo.py:373` sorted by `labeled_at` with a plain string key,
but the values now come in three shapes: `feedback_at` (UTC, space-separated), historical
`labeled_at` (local time, `T`-separated) and new `labeled_at` (UTC, space-separated). Since
`' ' < 'T'`, two rows from the same day can order wrongly against each other. Display-only,
no data risk. Sorting on `datetime(...)` in SQL, or parsing before the sort, would fix it.

## In Progress

(none)

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
