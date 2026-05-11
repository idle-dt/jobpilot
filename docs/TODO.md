# JobPilot — Master TODO

Roadmap, task tracking, bugs, and feature ideas for the JobPilot project.
This is the single source of truth for what needs to be done — check and update regularly.

## Bugs

- **Sync dot color after sync**: Sync dot stays red/orange instead of turning green after a successful sync — likely the `.syncing` class or color isn't being reset
- **False "Sync failed"**: Sync completes successfully (data fetched) but UI shows "Sync failed" — page refresh shows correct "Synced" state. Likely a JS timeout or response parsing issue
- **Dashboard Last Sync stale time**: Last Sync timestamp uses `received_at` (email date) instead of actual sync time, so it shows a stale value
- **Settings input field styling**: "Locations — Secondary" label/input visual layout is broken

## In Progress

Items with implementation prompts in `docs/prompts/` — see `PROMPTS.md` for status.

## Security

- **HIGH**: CSRF protection — install `Flask-WTF`, enable `CSRFProtect`, send token via HTMX header on all POST endpoints
- **HIGH**: Add SRI hashes to CDN scripts (HTMX, Pico CSS) or vendor them into `/static/`
- **MEDIUM**: Validate `email_id` parameter format in feedback route
- **MEDIUM**: Rate limiting / debounce on `/api/sync` endpoint

## UI Improvements

- Description block expand/collapse animation (smooth slide-in/slide-out)
- Dashboard: Noise Predictions comparison table (same layout as scoring predictions table, but for noise model)

## Planned Features

### Deployment & Hosting
- Dockerize the app (Dockerfile, docker-compose)
- Add production WSGI server (gunicorn)
- CI/CD pipeline for automated testing and deployment
- Environment-based configuration (dev / staging / production)

### Automated Email Fetching
- Replace manual "Sync" button with scheduled background fetching (APScheduler is already a dependency)
- Configurable fetch interval per user
- Notification when new jobs are found

### Application Tracker
- Build UI for the existing `applications` table (CRUD is in repository, no web routes yet)
- Pipeline view: Applied > Screen > Interview > Offer > Rejected
- Status change history and notes

### Job Board Scraping
- Expand beyond Gmail monitoring to direct job board scraping
- Support LinkedIn, Indeed, Wellfound saved searches
- Deduplication across email and scraped sources

### Expired Job Auto-Detection
- Auto-detect expired jobs via URL scraping (404/redirect) or date heuristic
- Manual toggle already implemented
