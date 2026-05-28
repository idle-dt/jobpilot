# JobPilot — Improvement Prompts Tracker

## Implemented (prompt files removed)

Web Auth & Sync, Sync Days Setting, Digest Parsing, Job vs Noise Filter, Open Origin & Source, Inbox UI Redesign, Confidence-Based Scraping, Dashboard Stats Expansion, ML Training Pipeline, Pill Toggle Component, Configurable Signals & Preferences, Noise Model Feature Expansion, Description Improvements, Signal Matching Accuracy, Security & Critical Fixes, Architecture Refactor, README & License, Security Hardening, Noise Predictions Table, ML Retrain Crash Fix, GBC Calibration, Browser Scraper (superseded by Scraper Refactor), Scraper Refactor, Application Tracker, Review Queue Counts.

## Not Yet Implemented

- [ ] **Job Title Tiers** — [PROMPT_job_title_tiers.md](PROMPT_job_title_tiers.md) — Split job_title into primary/secondary categories (like tech keywords), with weighted scoring and Settings UI
- [ ] **Async Sync** — [PROMPT_async_sync.md](PROMPT_async_sync.md) — Background thread sync pipeline with live per-step progress, survives page refresh, comprehensive logging, tech debt cleanup
- [ ] **Bugfixes Batch 1** — [PROMPT_bugfixes_batch_1.md](PROMPT_bugfixes_batch_1.md) — LinkedIn digest separator regex, Last Sync stale time, orphan email cards, non-job filter, ML class imbalance, tracker UX

## Future / Ideas

- Negation-aware signal matching (detect "Remote is NOT available", "no Flutter experience needed")
- Expired job auto-detection (manual toggle implemented, auto-detection via URL scraping or date heuristic deferred)
- Description block expand/collapse animation (smooth slide-in/slide-out)
- CDN scripts SRI hashes or vendoring
- Dockerize the app (Dockerfile, docker-compose, gunicorn)
