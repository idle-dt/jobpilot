# Noise Filter — Audit TODO

Security and quality findings from the code audit of the "Filter Platform Noise from Job Opportunities" feature.

## HIGH

- [ ] **JobDetector always returns `is_job=True`** — `job_detector.py:84` returns `(True, 0.0)` for unknown emails, so `is_job_related` is never `False` and the review queue filter has no effect. The whitelist sets confidence but doesn't actually filter anything. Decide: should unknown emails default to `False` (hidden until triaged), or stay `True` (visible) with confidence used for sorting? The PROMPT spec says "Unknown — show for review", so current behavior matches intent, but the `is_job_related = TRUE` filter in the query is then dead code. Either remove the filter or change the default.
- [ ] **`debug: bool = True` in config.py** — Debug mode is on by default. If deployed without `JOBPILOT_DEBUG=false`, the Werkzeug interactive debugger is exposed (allows arbitrary code execution from browser). Change default to `False`, document `JOBPILOT_DEBUG=true` in `.env.example`.
- [ ] **Exception message leaked in sync error** — `routes.py:184` returns `str(e)` to the client, which can expose internal paths and schema details. Replace with a generic message; the error is already logged via `logger.exception`.

## MEDIUM

- [ ] **No DB migration for `is_job_related` column** — Databases created before this feature lack the column. `CREATE TABLE IF NOT EXISTS` won't add it to existing tables. Add an `ALTER TABLE` migration check in `init_db()`.
- [ ] **Duplicate feedback records possible** — `user_feedback` has no UNIQUE constraint on `email_id`. Multiple clicks create duplicate rows, inflating `noise_count` stats. Either add `UNIQUE(email_id)` with `INSERT OR REPLACE`, or use `COUNT(DISTINCT email_id)` in the stats query.
- [ ] **`page` param not validated in `/emails`** — `routes.py:56` does `int(request.args.get("page", 1))` without catching `ValueError` or clamping to `>= 1`. Non-numeric or negative values cause 500s or undefined behavior.

## LOW

- [ ] **`body_text` param accepted but unused** — `job_detector.py:65` accepts `body_text` but never reads it. Either remove it or add a comment that it's reserved for the future ML classifier.
- [ ] **`JobDetector` is stateless** — The class has no `__init__` or instance state. A new instance is created per `fetch_new_emails` call. Either use module-level functions or instantiate once at module level in `fetcher.py`.
- [ ] **Missing negative test cases** — `test_job_detector.py` has no tests for `is_job=False` returns (because the detector never returns `False` currently). Once the HIGH finding above is resolved, add tests for: empty subject, non-platform sender, obvious noise subjects.
- [ ] **Google Alerts whitelist too broad** — Any "Google Alert" subject is whitelisted regardless of content. Acceptable if the user only has job-related Google Alerts, but could misclassify non-job alerts.
