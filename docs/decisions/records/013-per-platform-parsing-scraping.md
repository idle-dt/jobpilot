# ADR-013: Per-platform email parsing and scraping strategy

**Status:** accepted
**Date:** 2026-06-05
**Tags:** scraping, email, parsing, integration

## Context

JobPilot ingests jobs from several sources, and each one behaves differently:

- Some send **plain-text** digest emails, some send **HTML-only** emails where the
  text body is unusable, and one exposes a **public API** instead of email.
- Some job pages can be fetched with a plain HTTP request, some require a real
  browser (Cloudflare / JS rendering), and some actively **ban scrapers by IP**.

Treating every platform identically produced bad data (e.g. Wellfound's HTML
emails parsed by the generic text parser yielded titles like "Actively Hiring")
and wasted effort or got us blocked (scraping pages that reject automation).

This ADR records, in one place, the parsing and scraping decision for each
supported platform so future contributors know *why* a platform is handled the
way it is. It complements [ADR-001](001-playwright-scraping.md) (browser
scraping), [ADR-009](009-persistent-browser-profiles.md) (logged-in sessions),
and [ADR-011](011-digest-parsing.md) (digest splitting).

## Decision

Two independent axes per platform: **how its email is parsed**, and **whether /
how its job pages are scraped** for full descriptions. Scraping is gated by
`SCRAPABLE_DOMAINS` in `scraper/constants.py`; a platform absent from that map is
never fetched.

| Platform | Email parsing | Page scraping | Rationale |
|----------|---------------|---------------|-----------|
| **LinkedIn** | Text digest parser (`_parse_linkedin_digest`) | `requests` first, browser fallback | Plain HTTP succeeds ~98% of the time; browser only when blocked |
| **Glassdoor** | HTML digest parser (`_parse_glassdoor_digest`) | Browser-only | Cloudflare blocks plain HTTP every time, so skip the wasted request |
| **Wellfound** | HTML digest parser (`_parse_wellfound_digest`) | **None — never scrape** | Pages aggressively IP-ban scrapers; parse the alert email only |
| **Indeed** | Text digest parser (`_parse_indeed_digest`) | None | Email carries enough; pages are heavily bot-protected |
| **relocate.me / Google Alerts** | Generic digest parser | None | Low volume; generic URL+context extraction is sufficient |
| **ArbeitNow** | Not email — public JSON API (`arbeitnow.py`) | N/A (API returns full data) | Official API provides structured listings directly |

Key sub-decisions:

- **HTML vs text parsing** is chosen per platform. Wellfound and Glassdoor emails
  are HTML-structured; their plain-text bodies smush all fields together, so they
  get dedicated HTML parsers driven by each platform's markup signature (e.g.
  Wellfound job titles are a `font-size:14px; font-weight:700; color:#000` div).
- **Wellfound is parse-only.** Its job URL is the email's "Learn more" tracking
  redirect (`links.wellfound.com/s/c/...`), preferred over the
  `wellfound.com/company/<slug>` page; that URL is stored for the user to click
  but is **never auto-fetched**.
- **URLs from email HTML are untrusted.** Extracted hrefs are validated
  (scheme + parsed hostname) before storage.
- **Glassdoor dedups by content, not URL.** Glassdoor reissues a fresh
  `jobListingId` (hence a new URL) for the same posting in every daily digest, so
  the `scraped_jobs.url` UNIQUE constraint alone lets one posting accumulate as
  many rows. For this source only, `JobRepository.insert_scraped_job` dedups on
  `(title, company, location)`: a content match **refreshes the stored link to
  the newer URL** (so the Source link stays live) rather than inserting a
  duplicate, and `_parse_glassdoor_digest` also dedups within a single email. URL
  normalization to just `jobListingId` (`_clean_job_url`) additionally collapses
  same-listing copies. Other platforms keep plain URL-based dedup, where the same
  URL reliably identifies the same posting.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| One generic parser for all platforms | Produced corrupted fields for HTML-only emails (Wellfound, Glassdoor) |
| Scrape every platform's job pages | Wellfound/Indeed ban or block automation; wasted requests, IP bans, log noise |
| Scrape Wellfound via the logged-in browser (like Glassdoor) | Tried and reverted — Wellfound IP-bans even authenticated browser sessions |
| Drop email parsing and rely only on scraping | Many platforms only reach us by email; no public listing endpoint |

## Consequences

### Positive
- Each platform gets the cheapest reliable strategy; no wasted browser launches.
- Adding a platform is a localized change: a parser branch in `digest.py` and an
  optional `SCRAPABLE_DOMAINS` entry.
- Avoids IP bans by never fetching hostile platforms.

### Negative / Tradeoffs
- Parse-only platforms (Wellfound, Indeed) are scored on title + company only, so
  they score lower without description text and may fall below the review
  threshold.
- HTML parsers are coupled to each platform's email markup and can break if the
  sender redesigns its template.
- Glassdoor content-dedup treats two postings with an identical
  `(title, company, location)` as the same job, so a genuinely distinct reposting
  with the same title/company/location is merged; conversely it only carries over
  one user label per posting if the same listing was labeled differently across
  digests.

### Risks
- Markup-signature drift (e.g. Wellfound changing its title CSS) silently yields
  zero jobs for that platform until the parser is updated.

## Related

- ADRs: [ADR-001](001-playwright-scraping.md), [ADR-009](009-persistent-browser-profiles.md), [ADR-011](011-digest-parsing.md)
- Code: `src/jobpilot/gmail/digest.py`, `src/jobpilot/scraper/constants.py`, `src/jobpilot/scraper/browser.py`, `src/jobpilot/scraper/arbeitnow.py`
