# ADR-003: Flask + Jinja2 + htmx

**Status:** accepted
**Date:** 2026-05-07
**Tags:** frontend, backend

## Context

JobPilot needs a local web UI to review classified emails, give feedback,
trigger syncs/training, and track applications. The interactions are modest
(submit feedback, toggle a badge, swap a list) and the app is single-user on
localhost. We wanted SPA-like responsiveness — no full-page reloads for small
actions — without taking on the build tooling, state management, and complexity
of a JavaScript SPA framework.

## Decision

Use **Flask** as the web framework, **Jinja2** for server-side templates, and
**htmx 2.0** for progressive-enhancement interactivity.

- `create_app()` wires up templates, static files, CSRF (`flask-wtf`), and rate
  limiting (`flask-limiter`).
- `base.html` sets `hx-boost="true"` on `<body>`, so ordinary links navigate via
  AJAX swaps but degrade to full-page loads if htmx is unavailable.
- Small actions (feedback, preferences, expired toggle) use `hx-post` and swap in
  rendered partials; the server emits `HX-Trigger` events (e.g. `reviewCountChanged`)
  to update related UI.
- A `htmx:configRequest` listener injects the CSRF token into every htmx request.

Boosted navigation always returns **full page templates** (never partials), per
the project UI rules — only explicit `hx-post`/`hx-get` API endpoints return partials.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| React / Vue / Svelte SPA | Build pipeline, client state, and API layer are disproportionate for a single-user localhost tool. |
| Django | Heavier batteries-included framework; Flask's minimalism fits the small surface area. |
| Server-rendered templates with full page reloads only | Every feedback click reloading the whole page is a poor review-queue experience; htmx gives partial updates cheaply. |

## Consequences

### Positive
- Server-side rendering keeps logic in Python; no duplicated client/server models.
- htmx delivers partial updates and boosted navigation with almost no JS.
- Small dependency surface; fast to develop and reason about.

### Negative / Tradeoffs
- htmx attribute-driven flows are less familiar than component frameworks.
- Rich client-side interactivity (drag-drop, complex local state) would be awkward.

### Risks
- Partial vs full-page rendering rules must be followed carefully (boosted nav must return full pages) to avoid broken navigation.

## Related

- ADRs: [ADR-005](005-pico-css-theme.md) (Pico CSS theme on top of these templates)
- Code: `src/jobpilot/web/app.py`, `src/jobpilot/web/routes.py`, `src/jobpilot/web/templates/`
- Docs: `CLAUDE.md` (UI Work), `DESIGN.md`

> Note: the explicit reasoning for htmx over an SPA framework was not recorded in
> code; it is inferred here from the progressive-enhancement design (`hx-boost`,
> server-rendered partials) and the project's stated SPA-like-navigation goal.
