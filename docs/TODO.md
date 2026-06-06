# JobPilot — Master TODO

Roadmap, task tracking, bugs, and feature ideas for the JobPilot project.
This is the single source of truth for what needs to be done — check and update regularly.

## Bugs

(none)

## In Progress

(none)

## Tech Debt

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
- Gmail fetcher and client
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
