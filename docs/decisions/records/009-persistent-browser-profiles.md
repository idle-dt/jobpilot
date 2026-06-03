# ADR-009: Persistent browser profiles

**Status:** accepted
**Date:** 2026-05-14
**Tags:** scraping, browser

## Context

Browser scraping with Playwright (see [ADR-001](001-playwright-scraping.md)) hit a
wall on Glassdoor: anonymous, freshly-launched browser sessions get caught by
Cloudflare's challenge ("Just a moment…") and never reach the job content. A prior
headless attempt failed for the same reason — no logged-in session, obvious
automation fingerprint. The pages we need (LinkedIn, Glassdoor) are also gated
behind a logged-in account. We needed the scraper to present as the real user who
is already logged in, and to keep that session between runs.

## Decision

Launch a **persistent browser context** backed by an on-disk Chrome profile, reused
across runs, with a one-time manual login flow.

- `launch_persistent_context(user_data_dir=~/.jobpilot/browser-profile, channel="chrome", ...)`
  stores cookies, local storage, and auth state in a real profile directory, so the
  logged-in session survives between scrapes.
- A manual `login(site)` flow opens a **visible** window, lets the user log in, and
  waits for them to close it — after which the session persists in the profile.
- Automation fingerprint is reduced with `--disable-blink-features=AutomationControlled`,
  a realistic user-agent and viewport, and randomized human-like delays between actions.
- A stale Chrome `SingletonLock` left by a prior crashed run is cleared before launch.

The net effect: Playwright drives the user's real, logged-in Chrome session and
looks like a normal person browsing — which gets past Cloudflare where an anonymous
session does not.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Anonymous `browser.launch()` per run | Caught by Cloudflare; not logged in, so gated content is unreachable. |
| Storing/replaying cookies manually (storage state JSON) | More brittle than a full persistent profile; misses other session state and fingerprint signals. |
| Solving the CF challenge programmatically / CAPTCHA services | Fragile, arms-race, and ethically/practically dubious; reusing the real session sidesteps the need. |

## Consequences

### Positive
- Reuses the user's logged-in session to reach gated pages and bypass Cloudflare.
- One manual login persists across many subsequent scrapes.
- Realistic fingerprint + human delays reduce bot detection.

### Negative / Tradeoffs
- Requires an interactive, visible login step the first time (and re-login when sessions expire).
- The profile directory holds real auth state on disk — sensitive data to protect.
- Single profile means scrapes are effectively serialized (one Chrome lock).

### Risks
- Expired/invalidated sessions silently degrade scraping until the user re-logs in.
- A crashed run can leave a stale lock (handled by explicit cleanup).

## Related

- ADRs: [ADR-001](001-playwright-scraping.md) (Playwright browser scraping)
- Specs: `docs/specs/SPEC_GLASSDOOR_BROWSER_SCRAPING.md`
- Code: `src/jobpilot/scraper/browser.py`
- Commits: `2d10feb` (persistent context), `6111dce` (Glassdoor session, lock cleanup, login timeout)
