# ADR-001: Playwright for job page scraping

**Status:** accepted
**Date:** 2026-05-14
**Tags:** scraping, browser

## Context

Job listings on the major boards (LinkedIn, Glassdoor) are rendered client-side
and/or sit behind anti-bot protection (Cloudflare challenge pages). A plain HTTP
fetch returns either an empty shell with no job content or a "Just a moment…"
interstitial, so the generic `requests` + BeautifulSoup page scraper cannot read
the job description. We needed a way to load these pages the way a real browser
does — running JavaScript and presenting as a normal user — to extract titles,
companies, and descriptions for scoring.

## Decision

Use [Playwright](https://playwright.dev/python/) (Chromium) as a browser-based
scraper fallback for JS-rendered job pages. The scraper navigates with
`page.goto(url, wait_until="domcontentloaded")` followed by
`page.wait_for_load_state("load")` so the DOM is fully built before extraction,
then dispatches to domain-specific extractors (LinkedIn, Glassdoor, generic).
Cloudflare challenge pages are detected via title/content markers and skipped
gracefully rather than scraped as garbage.

Playwright is imported lazily with a clear install hint, since it is an optional
heavy dependency (`poetry add playwright && playwright install chromium`).

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| `requests` + BeautifulSoup (the existing generic scraper) | Returns no content for JS-rendered pages and is blocked by Cloudflare. Kept for static/API pages, not viable for LinkedIn/Glassdoor. |
| Selenium / WebDriver | Heavier driver management, slower API, weaker auto-waiting; Playwright's `wait_for_load_state` and persistent-context support fit the use case better. |
| Third-party scraping API (ScrapingBee, Bright Data) | External paid service, sends URLs/data off the local machine — conflicts with the project's local-first design. |

## Consequences

### Positive
- Reads JavaScript-rendered job pages that the HTTP scraper cannot.
- Domain-specific extractors give clean title/company/description fields.
- Pairs with a persistent logged-in profile (see [ADR-009](009-persistent-browser-profiles.md)) to look like a real user.

### Negative / Tradeoffs
- Heavy optional dependency: a full Chromium download (~hundreds of MB).
- Slower than an HTTP request (page load + human-like delays).
- Requires a real Chrome/Chromium channel available on the host.

### Risks
- Anti-bot defenses evolve; Cloudflare detection markers may need updating over time.
- Site DOM changes break the per-domain extractors.

## Related

- ADRs: [ADR-009](009-persistent-browser-profiles.md) (persistent browser profiles)
- Specs: `docs/specs/SPEC_GLASSDOOR_BROWSER_SCRAPING.md`
- Code: `src/jobpilot/scraper/browser.py`
- Commits: `2d10feb` (initial Playwright fallback), `6111dce` (Glassdoor via persistent session)
