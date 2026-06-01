# JobPilot — Master TODO

Roadmap, task tracking, bugs, and feature ideas for the JobPilot project.
This is the single source of truth for what needs to be done — check and update regularly.

## Bugs

- **ML scoring model collapse**: GBC/SVM/LR predict majority class only (0% precision/recall) — code fix applied (`class_weight="balanced"`), needs retrain via ML Experiment Lab

## In Progress

See `docs/specs/SPECS.md` for spec implementation status.

## UI Improvements

- Description block expand/collapse animation (smooth slide-in/slide-out)

## Planned Features

### Classification
- Salary threshold scoring — penalize jobs with salary below user's minimum
- Negation-aware signal matching — detect "Remote is NOT available", "no Flutter experience needed"

### Expired Job Auto-Detection
- Auto-detect expired jobs via URL scraping (404/redirect) or date heuristic
- Title mismatch detection on re-scrape — if the scraped title no longer matches the stored title, the listing was recycled/reposted
- Manual toggle already implemented

### Deployment & Hosting
- Dockerize the app (Dockerfile, docker-compose)
- Add production WSGI server (gunicorn)
- CI/CD pipeline for automated testing and deployment
- Environment-based configuration (dev / staging / production)
