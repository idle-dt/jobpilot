# JobPilot — Master TODO

Roadmap and task tracking for the JobPilot project.

## In Progress

### Noise Filter (Job vs Noise Detection)
Whitelist-based job detector, "Not a Job" feedback button, and noise stats.
- **Status**: Core feature implemented (whitelist, UI button, keyboard shortcut, stats).
- **Next steps**: [TODO_noise_filter.md](todos/TODO_noise_filter.md) — 10 tasks from security/quality audit (3 HIGH, 3 MEDIUM, 4 LOW).

### Web Auth & Sync
Web-based Google OAuth login, auth gate, and manual email sync from the browser.
- **Status**: Core flow implemented (login, sync, logout). Single-user only.
- **Next steps**: [TODO_web_auth_and_sync.md](todos/TODO_web_auth_and_sync.md) — 16 tasks covering multi-user support, security hardening, and production readiness.

### Security Hardening (from UI redesign audit)
- **HIGH**: Add CSRF protection — install `Flask-WTF`, enable `CSRFProtect`, send token via HTMX header on all POST endpoints
- **HIGH**: Add SRI hashes to CDN scripts (HTMX, Pico CSS) or vendor them into `/static/`
- **HIGH**: Replace raw f-string HTML in `toggle_expired` route with `render_template_string`
- **MEDIUM**: Validate `email_id` parameter format in feedback route
- **MEDIUM**: Add rate limiting / debounce on `/api/sync` endpoint
- **LOW**: Consistent date formatting for `scraped_at` (use `.strftime()` instead of string slicing)

### Dashboard — Noise Predictions Table
- Add a "Recent Noise Predictions Comparison" table to the Stats/Dashboard page (same layout as the existing "Recent Predictions Comparison" table, but showing noise model predictions instead of scoring model predictions)

### UI Known Issues
- **Sync now right margin**: "Sync now" text in page heading does not align with card content right edge (Pico `<article>` padding mismatch)
- **Page flicker on navigation**: Full-page reload causes visible flash/blink when switching between Inbox, Emails, Stats, Settings. Consider HTMX `hx-boost` for SPA-like navigation or add a CSS transition to smooth page loads.
- **Sync dot color after sync**: Sync dot stays red/orange instead of turning green after a successful sync — likely the `.syncing` class or color isn't being reset
- **"Nothing to review" above visible cards**: Empty-state message shows even when scraped job cards are visible below it
- **Dashboard Last Sync stale time**: Last Sync timestamp uses `received_at` (email date) instead of actual sync time, so it shows a stale value
- **False "Sync failed"**: Sync completes successfully (data fetched) but UI shows "Sync failed" — page refresh shows correct "Synced" state. Likely a JS timeout or response parsing issue

## Planned

### Deployment & Hosting
- Dockerize the app (Dockerfile, docker-compose)
- Add production WSGI server (gunicorn)
- CI/CD pipeline for automated testing and deployment
- Environment-based configuration (dev / staging / production)

### Automated Email Fetching
- Replace manual "Sync" button with scheduled background fetching (APScheduler is already a dependency)
- Configurable fetch interval per user
- Notification when new jobs are found

### Job Board Scraping
- Expand beyond Gmail monitoring to direct job board scraping
- Support LinkedIn, Indeed, Wellfound saved searches
- Deduplication across email and scraped sources

### ML Classification
- Train a user-specific model from feedback labels (infrastructure exists: `min_training_samples`, `retrain_after_n_labels` in config)
- Replace or augment rule-based scorer with ML predictions
- A/B scoring comparison (rule-based vs ML) on the stats page

### Application Tracker
- Build UI for the existing `applications` table (CRUD is in repository, no web routes yet)
- Pipeline view: Applied > Screen > Interview > Offer > Rejected
- Status change history and notes

### Settings Page
- Currently has only sync_days — populate with more user preferences
- Configurable scoring weights, fetch interval, monitored domains
- Account management (connected Gmail accounts, token status)
