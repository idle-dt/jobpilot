# JobPilot — Master TODO

Roadmap, task tracking, bugs, and feature ideas for the JobPilot project.
This is the single source of truth for what needs to be done — check and update regularly.

## Bugs

(none)

## In Progress

(none)

## Tech Debt

### Application status vocabulary is duplicated across 4 places

The set of valid application statuses is declared independently in four locations,
with no single source of truth:

| Location | Form | File |
|----------|------|------|
| `APPLICATION_STATUSES` | tuple of status strings | `services/tracker_service.py` |
| `STATUS_LABELS` | dict keyed by status | `services/tracker_service.py` |
| `STATUS_SORT_RANK` | dict keyed by status | `services/tracker_service.py` |
| `CHECK(status IN (...))` | SQL constraint (appears twice: `SCHEMA_SQL` + the rebuild migration) | `storage/database.py` |

**Why it's a problem:** adding or renaming a status requires editing all four (five,
counting the migration's duplicate CHECK). They can silently drift apart.

**Concrete latent bug:** if a status is added to `APPLICATION_STATUSES` but not to
`STATUS_SORT_RANK`, it falls through to the `_UNKNOWN_STATUS_RANK = 99` fallback and
silently sorts to the bottom of the tracker — no error, no warning. There is currently
no test guarding that the two stay in sync.

**Note on placement:** the sort order (`STATUS_SORT_RANK`) is correctly in the service
layer — it's a business rule (which applications need attention first), not persistence
or presentation, and it's co-located with the other status constants. The issue is the
*duplication*, not the location. Moving the order out of the service would not help.

**Options (cheapest first):**

1. **Parity guard (recommended near-term).** Add a test asserting
   `set(STATUS_SORT_RANK) == set(APPLICATION_STATUSES)` (and that `STATUS_LABELS` covers
   the same set). One line, catches drift, near-zero cost. Does not remove the duplication
   but makes it safe.
2. **Single source of truth (larger refactor).** Introduce an `ApplicationStatus` enum or
   registry where each member carries `value + label + rank + is_terminal`, and derive the
   tuple, labels, rank map, and the SQL CHECK list from it. Eliminates the duplication
   entirely. Touches templates (which iterate `statuses` / `status_labels`) and the schema
   CHECK generation. Worth doing only if the status set keeps growing.

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
