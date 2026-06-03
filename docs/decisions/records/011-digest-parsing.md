# ADR-011: Digest parsing for multi-job emails

**Status:** accepted
**Date:** 2026-05-07
**Tags:** email, parsing

## Context

The job-board emails JobPilot ingests (see [ADR-007](007-gmail-api.md)) are mostly
**digests**: a single email containing many job listings. To score and track jobs
individually, each digest must be split into separate `(title, company, location,
url)` records. Every platform formats its digest differently — LinkedIn uses
plain-text blocks, Glassdoor puts listings only in HTML, Indeed uses its own layout —
and all of them surround real listings with boilerplate ("Apply Now", "View job"),
tracking-laden URLs, and noise.

## Decision

Implement **platform-specific digest parsers** behind a single `parse_digest(email)`
dispatcher in `gmail/digest.py`, with a generic fallback.

- **LinkedIn** (`_parse_linkedin_digest`): split the plain-text body on separator
  lines / triple newlines into blocks; pull title/company/location from lines before
  each "View job" URL.
- **Indeed** (`_parse_indeed_digest`): split on triple newlines; find Indeed URLs and
  read surrounding content lines.
- **Glassdoor** (`_parse_glassdoor_digest`): parse the **HTML** (Glassdoor job links
  live in HTML, not plain text); walk up the DOM from each job link to its containing
  card and extract title/company/location/salary.
- **Generic** (`_parse_generic_digest`): regex-match known job-platform URLs and read
  the preceding context lines.

Shared helpers filter boilerplate lines (`_is_boilerplate_line`), strip tracking
parameters from URLs (`_clean_job_url`), and only emit a job when a URL and a
non-boilerplate title are both present. Tunable thresholds (max boilerplate line
length, DOM walk depth, min jobs for generic) keep extraction robust.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| One universal parser for all platforms | Digest formats differ too much (plain-text vs HTML-only); a single heuristic produces garbage on at least one platform. |
| LLM-based extraction | Cost, latency, and sending email content to an external service — against the local-first design. |
| Treat each digest as a single "job" | Loses the individual listings entirely; defeats per-job scoring and tracking. |

## Consequences

### Positive
- Reliable per-job extraction tuned to each platform's real format.
- Tracking-parameter stripping yields clean, deduplicable URLs.
- Generic fallback handles unknown senders without a dedicated parser.

### Negative / Tradeoffs
- One parser per platform to maintain; new platforms need new parsers.
- Heuristic thresholds are sensitive and may need tuning.

### Risks
- Platform email/HTML redesigns silently break the corresponding parser until noticed.

## Related

- ADRs: [ADR-007](007-gmail-api.md) (Gmail source of the digest emails)
- Code: `src/jobpilot/gmail/digest.py`, `src/jobpilot/gmail/parser.py`

> Note: the specific heuristic thresholds (line lengths, DOM walk depth) and the
> per-platform splitting choices are read from the code; the reasoning behind exact
> values was largely not recorded.
