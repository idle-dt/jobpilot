# JobPilot

## Project

Local job search autopilot — monitors Gmail for job digest emails, scrapes job boards, classifies listings with rule-based scoring, and tracks applications. Python/Flask backend, Jinja2 + htmx frontend, SQLite storage.

## Commands

- `scripts/test_summary.sh` — run all tests, failures only, output capped at 60 lines
- `poetry run pytest tests/` — run all tests (full output)
- `PYTHONPATH=src python -m jobpilot serve` — run dev server on :5050
- `poetry run ruff check src/` — lint

## Architecture

- **Routes** (`web/routes.py`) -> **Services** (`services/`) -> **Repositories** (`storage/*_repo.py`)
- Classifier pipeline: `signals.py` (keyword definitions) -> `features.py` (score functions) -> `rules.py` (weighted scorer)
- Gmail pipeline: `fetcher.py` (API calls) -> `parser.py` (extract fields) -> `digest.py` (split digests into individual jobs)
- Scraper: `job_page.py` (generic page scraper) + `arbeitnow.py` (API integration)
- ML: `classifier/ml_trainer.py` (train and predict with scikit-learn models) + `services/ml_service.py` (training triggers)

## UI Work

**Before any UI changes, read `DESIGN.md`** — it documents the design system: warm cream canvas, ink black CTAs, pill-shaped components, Sofia Sans typography, and the full color palette.

- Theme toggle: `data-theme="light"` / `data-theme="dark"`, persisted to `localStorage`
- All URLs in `href` attributes must be validated (`http://` or `https://` only)
- Do NOT return partials for boosted navigation — always return full page templates

## Task Tracking

- **`docs/TODO.md`** — Master task board. All bugs, issues, features, and planned work live here. Check and update it when picking up or completing work.
- **`docs/specs/SPEC_*.md`** — Individual implementation specs. Use `docs/specs/SPEC_TEMPLATE.md` as the starting point for new specs. Track active specs in `docs/TODO.md` under "In Progress".

## Implementation Workflow

When implementing a feature from `docs/specs/SPEC_*.md`:

1. **Plan** — Read the spec file. Ask if the spec is ambiguous; proceed if detailed and specific.
2. **Implement** — Write the code following the spec and the rules in this file.
3. **Verify** — Run the Verification section from the spec: automated checks (`pytest`, `ruff`), then logic verification assertions, then integration checks if listed. Fix any failures before declaring done.
4. **Report** — Fill in the Implementation Report section of the spec: what was done, any deviations from the original spec, additional unplanned changes, and decisions made during implementation. Include this report in the final message.

## Specs and ADRs

Writing a spec or an ADR: use the `specs-and-adrs` skill. `/ship` lives in `.claude/commands/ship.md`.

## Code Rules

### Quality
- No magic numbers/strings — use named constants
- Max 30 lines per function, max 300 lines per file
- Type hints on all function signatures
- Docstrings on all public classes and methods
- No bare `except Exception:` — catch specific types
- No `repo.conn.execute()` outside repository classes
- No business logic in route handlers — use service layer
- No inline HTML responses — use `render_template()`

### Security
- Parameterized SQL only — no string interpolation or f-strings in SQL
- Never use `|safe` on user/scraped data — Jinja2 autoescapes
- Validate URL schemes in `href` attributes (prevent `javascript:` XSS)
- Validate scraper URLs (reject private IPs, non-HTTP schemes, unsafe redirects)
- Validate query parameters against allowlists
- JS: use `createElement`/`createTextNode` — never `innerHTML` with dynamic data
- Never expose internal error details to users — log full exception, flash generic message

### ML
- Seed random operations for reproducibility
- Feature names as constants
- Document hyperparameters
