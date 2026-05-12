# JobPilot — Improvement Prompts Tracker

## Implemented

- [x] **Web Auth & Sync** — [PROMPT_web_auth_and_sync.md](PROMPT_web_auth_and_sync.md) — OAuth login flow, Sync button, auth gate
- [x] **Sync Days Setting** — [PROMPT_sync_days_setting.md](PROMPT_sync_days_setting.md) — Configurable sync period in Settings UI
- [x] **Digest Parsing** — [PROMPT_digest_parsing.md](PROMPT_digest_parsing.md) — Parse LinkedIn digests into individual job cards, boilerplate filtering
- [x] **Job vs Noise Filter** — [PROMPT_job_vs_noise_filter.md](PROMPT_job_vs_noise_filter.md) — Whitelist + "Not a Job" button + ML (future)
- [x] **Open Origin & Source** — [PROMPT_open_origin_and_source.md](PROMPT_open_origin_and_source.md) — Two buttons: Open Origin (job link) + Open Source (Gmail email)

- [x] **Inbox UI Redesign** — Compact row cards, warm charcoal + dark bronze theme, semantic color system, inline sync, signal cap at 5 with expand/collapse, right-aligned action buttons with spacer, security fixes (XSS, error leak, JSON parse)
- [x] **Confidence-Based Scraping** — [PROMPT_confidence_scraping.md](PROMPT_confidence_scraping.md) — Scrape full job descriptions only for ambiguous scores (0.3-0.8), re-score with full text, platform-specific parsers, SSRF protection, configurable threshold
- [x] **Dashboard Stats Expansion** — [PROMPT_dashboard_stats.md](PROMPT_dashboard_stats.md) — Chart.js dashboard: sources donut, classification/labels, score/confidence histograms, ML readiness progress, trend line, top locations, labels-vs-rules agreement
- [x] **ML Training Pipeline** — [PROMPT_ml_training.md](PROMPT_ml_training.md) — Train 4 scikit-learn algorithms (LR, RF, GBC, SVM) for both noise and scoring models; per-job prediction badges on cards; ML Experiment Lab on stats page; export model data; auto-train + manual retrain
- [x] **Pill Toggle Component** — [PROMPT_pill_toggle_component.md](PROMPT_pill_toggle_component.md) — Ink black pill toggle switch for boolean settings; CSS-only with native checkbox; light/dark theme; update DESIGN.md

- [x] **Configurable Signals & Preferences** — [PROMPT_configurable_signals.md](PROMPT_configurable_signals.md) — Settings UI for search preferences (tech keywords, job titles, seniority, locations, salary), monitored platforms checklist, score threshold slider; dedicated `user_preferences` table; ML model invalidation on preference change; ArbeitNow API integration
- [x] **Noise Model Feature Expansion** — [PROMPT_noise_model_features.md](PROMPT_noise_model_features.md) — Progressive structural features for noise model (digest_job_count, url_count, body_length + 4 more at 60 labels); tier system, overfit detection, auto-retrain on tier transition
- [x] **Description Improvements** — [PROMPT_description_improvements.md](PROMPT_description_improvements.md) — Preserve formatting, strip "show more" artifacts, highlight matched signals (green/red) in description text
- [x] **Signal Matching Accuracy** — [PROMPT_signal_matching_accuracy.md](PROMPT_signal_matching_accuracy.md) — Word boundary matching to prevent substring false positives (intern/internet), title-scoped seniority to avoid context-blind negatives

- [x] **Security & Critical Fixes** — [PROMPT_security_critical_fixes.md](PROMPT_security_critical_fixes.md) — SQL parameterization, inline HTML→partials, OAUTHLIB guard, narrow exception catches, ruff fixes, debug default
- [x] **Architecture Refactor** — [PROMPT_architecture_refactor.md](PROMPT_architecture_refactor.md) — Split repository.py into focused repos, extract services from routes, remove direct conn.execute, fix email._signals hack, type hints, docstrings
- [x] **README & License** — [PROMPT_readme.md](PROMPT_readme.md) — Portfolio-quality README with screenshots, badges, architecture overview, getting started guide, MIT license
- [x] **Security Hardening** — [PROMPT_security_hardening.md](PROMPT_security_hardening.md) — CSRF protection (Flask-WTF), Chart.js SRI hash, email_id validation, sync rate limiting (Flask-Limiter)
- [x] **Noise Predictions Table** — [PROMPT_noise_predictions_table.md](PROMPT_noise_predictions_table.md) — Predictions comparison table for noise model on stats dashboard
- [x] **ML Retrain Crash Fix** — [PROMPT_ml_retrain_crash.md](PROMPT_ml_retrain_crash.md) — Run auto-retrain in subprocess to survive segfaults, add class imbalance guards, zero_division scoring

## Not Yet Implemented

## Future / Ideas

- Expired job auto-detection (manual toggle implemented, auto-detection via URL scraping or date heuristic deferred)
- Web scrapers for job boards (Phase 4 of main plan)
- Application tracker / kanban (Phase 4 of main plan)
- CSRF protection across all POST endpoints (Flask-WTF)
- Settings input field styling broken — "Locations — Secondary" label/input visual issue
- Description block expand/collapse animation (smooth slide-in/slide-out)
- CDN scripts SRI hashes or vendoring
