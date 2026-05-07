# JobPilot

## Project

Local job search autopilot — monitors Gmail for job digest emails, scrapes job boards, classifies listings with rule-based scoring, and tracks applications. Python/Flask backend, Jinja2 + htmx frontend, SQLite storage.

## Stack

- Python 3.11+, Flask 3, Pydantic Settings
- Jinja2 templates, Pico CSS v2, htmx 2.0 (`hx-boost="true"` for SPA-like navigation)
- Sofia Sans font (Google Fonts) at weights 450/500/700
- SQLite with WAL mode
- Poetry for dependency management
- pytest for testing

## Commands

- `poetry run pytest tests/` — run all tests
- `PYTHONPATH=src python -m jobpilot serve` — run dev server on :5050
- `poetry run ruff check src/` — lint

## UI Work

**Before any UI changes, read `DESIGN.md`** — it documents the Mastercard-inspired design system: warm cream canvas, ink black CTAs, pill-shaped components, Sofia Sans typography, and the full color palette. Follow it strictly to maintain visual consistency.

Key implementation details:
- Theme toggle: `data-theme="light"` (default) / `data-theme="dark"`, persisted to `localStorage`
- CSS vars defined in `:root` / `[data-theme="light"]` and `[data-theme="dark"]` blocks
- All URLs rendered in `href` attributes must be validated (`http://` or `https://` only)
- Navigation is a floating pill (`nav.nav-pill`), not Pico's default `<nav>`
- Sort/filter links use plain `<a href>` — `hx-boost` handles smooth transitions
- Do NOT return partials for boosted navigation — always return full page templates
- Inbox layout: toolbar card (`.toolbar-card`) above heading row (`.heading-row`), see DESIGN.md
- Job cards use two-column layout (`.card-top` > `.card-main` + `.card-aside`)
- Sync button overrides Pico CSS button defaults with `!important` — keep these when modifying
- Use `visibility: hidden` (not `display: none`) to hide elements that must hold their layout space

## Security Notes

- Scraper validates URLs before fetching (rejects private IPs, non-HTTP schemes, unsafe redirects)
- Template `href` attributes check URL scheme to prevent `javascript:` XSS
- All SQL uses parameterized queries — no string interpolation
- Scraped content is autoescaped by Jinja2 — never use `|safe` filter on user/scraped data
- Query parameters validated against allowlists (e.g. `sort` param in inbox route)
- JS uses safe DOM methods (`createElement`/`createTextNode`) — never `innerHTML` with dynamic data
