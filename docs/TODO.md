# JobPilot — Master TODO

Roadmap, task tracking, bugs, and feature ideas for the JobPilot project.
This is the single source of truth for what needs to be done — check and update regularly.

## Bugs

- **Sync dot color after sync**: Sync dot stays red/orange instead of turning green after a successful sync — likely the `.syncing` class or color isn't being reset
- **False "Sync failed"**: Sync completes successfully (data fetched) but UI shows "Sync failed" — page refresh shows correct "Synced" state. Likely a JS timeout or response parsing issue
- **Dashboard Last Sync stale time**: Last Sync timestamp uses `received_at` (email date) instead of actual sync time, so it shows a stale value
- **Settings input field styling**: "Locations — Secondary" label/input visual layout is broken

## In Progress

- **Application Tracker** — UI for existing `applications` table (branch: `feat/application-tracker`)

See `docs/prompts/PROMPTS.md` for prompt implementation status.

## UI Improvements

- Description block expand/collapse animation (smooth slide-in/slide-out)

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

### Expired Job Auto-Detection
- Auto-detect expired jobs via URL scraping (404/redirect) or date heuristic
- Manual toggle already implemented
