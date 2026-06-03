# JobPilot — Spec Tracker

## Implemented (spec files removed)

Web Auth & Sync, Sync Days Setting, Digest Parsing, Job vs Noise Filter, Open Origin & Source, Inbox UI Redesign, Confidence-Based Scraping, Dashboard Stats Expansion, ML Training Pipeline, Pill Toggle Component, Configurable Signals & Preferences, Noise Model Feature Expansion, Description Improvements, Signal Matching Accuracy, Security & Critical Fixes, Architecture Refactor, README & License, Security Hardening, Noise Predictions Table, ML Retrain Crash Fix, GBC Calibration, Browser Scraper, Scraper Refactor, Application Tracker, Review Queue Counts, Job Title Tiers, Async Sync, Bugfixes Batch 1, Salary Threshold Scoring, Negation-Aware Signal Matching.

## Implemented (kept as project documentation)

- [Glassdoor Browser Scraping](SPEC_GLASSDOOR_BROWSER_SCRAPING.md) — switch Glassdoor to browser-only strategy with Cloudflare-aware fallback; captures the rationale for picking `BROWSER_ONLY` over `REQUESTS_THEN_BROWSER` based on observed success rates.

## Not Yet Implemented

(none)

## Future / Ideas

- Negation-aware signal matching (detect "Remote is NOT available", "no Flutter experience needed")
- Expired job auto-detection (manual toggle implemented, auto-detection via URL scraping or date heuristic deferred)
- Description block expand/collapse animation (smooth slide-in/slide-out)
- CDN scripts SRI hashes or vendoring
- Dockerize the app (Dockerfile, docker-compose, gunicorn)
