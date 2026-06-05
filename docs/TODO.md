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

### Security: CSRF token missing in `updateArbeitnow()`

`settings.html:320-325` — the `updateArbeitnow()` JS function sends a POST without the
`X-CSRFToken` header. Every other POST in the same file (`updatePreference`, `loginBrowser`)
includes it. One-line fix: add `'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content`
to the fetch headers.

### Security: Missing `rel="noopener noreferrer"` on external links

8 `target="_blank"` links across `review_queue.html`, `stats.html`, and `login.html` are
missing `rel="noopener noreferrer"`. The tracker modal (`tracker_modal.html:84`) has it —
the rest don't. Allows reverse tabnabbing where the opened page can navigate the opener via
`window.opener`. Mechanical fix across all templates.

### Bare `except Exception:` in 4 places

Per CLAUDE.md rule: *"catch specific types"*. Current violations:

| File | Line | Context | Should catch |
|------|------|---------|--------------|
| `gmail/parser.py` | 66 | Date parsing | `ValueError` |
| `gmail/auth.py` | 53 | Credential check | `json.JSONDecodeError, FileNotFoundError` |
| `web/app.py` | 91 | Auth middleware | `KeyError, AttributeError` |
| `web/sync_routes.py` | 103 | Sync thread boundary | Keep as fallback, but add specific catches first |

### Business logic in route handlers

`web/routes.py` has significant business logic that should be in service layer:

- `inbox()` (lines 66–141, 76 lines) — builds review items, attaches predictions, aggregates counts
- `ml_export()` (lines 526–631, 105 lines) — full export pipeline with feature extraction, metrics, disagreement detection
- `settings_page()` (lines 260–301) — domain merging, preference transformation

These are untestable without HTTP request context. Extract to `InboxService`, `MLExportService`.

### Files over 300-line limit

| File | Lines | Notes |
|------|-------|-------|
| `storage/database.py` | 713 | Migrations keep growing; extract to `storage/migrations.py` |
| `web/routes.py` | 631 | Split into blueprints or extract service methods |
| `gmail/digest.py` | 595 | Per-platform parsers could be separate modules |
| `classifier/ml_trainer.py` | 468 | `_train_single()` alone is 76 lines |

### Long functions (>30 lines)

| Function | File | Lines |
|----------|------|-------|
| `inbox()` | `web/routes.py` | 76 |
| `ml_export()` | `web/routes.py` | 105 |
| `_train_single()` | `classifier/ml_trainer.py` | 76 |
| `_predict_all()` | `classifier/ml_trainer.py` | 55 |
| `create_app()` | `web/app.py` | 77 |
| `fetch_new_emails()` | `gmail/fetcher.py` | 59 |
| `_parse_glassdoor_digest()` | `gmail/digest.py` | 81 |
| `_run_scrape_batch()` | `services/sync_service.py` | 92 |

### `console.log()` debug statements left in production

`stats.html` lines 1001–1016 contain 5 `console.log('[ML] ...')` calls that expose internal
model structure details. Should be removed or gated behind a debug flag.

### Inconsistent SQLite `busy_timeout` values

`storage/database.py` sets `busy_timeout=5000` (5s) on connection init, but
`web/sync_routes.py` overrides with `PRAGMA busy_timeout=30000` (30s) for sync threads.
The override is also done via raw `conn.execute()` in route handlers — outside the
repository layer. Should be a single configurable value applied in `get_connection()`.

### Test coverage is thin

Only 7 test modules exist, covering parsers, rules, digest, and storage basics.
**No test coverage at all** for:

- All route handlers (`web/routes.py`, `tracker_routes.py`, `sync_routes.py`)
- Services (`classification_service.py`, `sync_service.py`, `ml_service.py`)
- ML pipeline (`ml_trainer.py`, `ml_prediction.py`)
- Gmail fetcher and client
- Repositories (`app_repo.py`, `email_repo.py`, `ml_repo.py`, `predictions_repo.py`)

Core business logic is essentially untested. Priority: services and route handlers.

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
