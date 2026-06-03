# JobPilot — Spec Tracker

## Implemented (spec files removed)

Web Auth & Sync, Sync Days Setting, Digest Parsing, Job vs Noise Filter, Open Origin & Source, Inbox UI Redesign, Confidence-Based Scraping, Dashboard Stats Expansion, ML Training Pipeline, Pill Toggle Component, Configurable Signals & Preferences, Noise Model Feature Expansion, Description Improvements, Signal Matching Accuracy, Security & Critical Fixes, Architecture Refactor, README & License, Security Hardening, Noise Predictions Table, ML Retrain Crash Fix, GBC Calibration, Browser Scraper, Scraper Refactor, Application Tracker, Review Queue Counts, Job Title Tiers, Async Sync, Bugfixes Batch 1, Salary Threshold Scoring, Negation-Aware Signal Matching, Email Description Display.

## Not Yet Implemented

- Parsing & Signal Fixes — boilerplate false positives, Glassdoor rating parsing, "distributed" remote synonym (`SPEC_DIGEST_PARSING_FIXES.md`)
- Glassdoor Browser Scraping — use logged-in Playwright session to scrape Glassdoor descriptions (`SPEC_GLASSDOOR_BROWSER_SCRAPING.md`)

## Future / Ideas

- Negation-aware signal matching (detect "Remote is NOT available", "no Flutter experience needed")
- Expired job auto-detection (manual toggle implemented, auto-detection via URL scraping or date heuristic deferred)
- Description block expand/collapse animation (smooth slide-in/slide-out)
- CDN scripts SRI hashes or vendoring
- Dockerize the app (Dockerfile, docker-compose, gunicorn)
