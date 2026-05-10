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

## Implementation Workflow

When implementing a feature from `docs/prompts/PROMPT_*.md`:

1. **Plan** — Read the prompt file. Ask as many clarifying questions as needed before writing code. Do NOT make decisions autonomously — if anything is ambiguous, unclear, or has multiple approaches, stop and ask. The user would rather answer 50 questions than discover 5 wrong assumptions.
2. **Implement** — Write the code following the prompt spec and the rules in this file.
3. **Test** — Run `poetry run pytest tests/` and `poetry run ruff check src/`. Fix any failures before declaring done.

## /ship Command

When the user says `/ship`, execute this flow in order. Stop and report if any step fails.

1. **Test** — Run `poetry run pytest tests/` and `poetry run ruff check src/`. If either fails, report the failures and stop. Do not proceed until all tests and lint pass.
2. **Quality & Security Audit** — Spawn a code-reviewer agent to check all changed files for:
   - Python: type hints, docstrings on public APIs, max 30 lines per function, no magic numbers/strings, no bare `except Exception`, no dead code
   - Security: parameterized SQL only, no inline HTML responses, no `|safe` on dynamic data, URL validation on hrefs
   - ML: seeded random operations, feature names as constants, documented hyperparameters
   - Web: DESIGN.md compliance, dark theme support, accessible markup
   Report findings with severity. Block on any HIGH or CRITICAL issues — prompt the user to fix before continuing. MEDIUM issues are reported but don't block.
3. **Branch** — Create a new branch from current HEAD. Naming: `feat/<prompt-name>` for features, `fix/<prompt-name>` for fixes, `refactor/<prompt-name>` for refactors. One prompt = one branch.
4. **Commit** — Stage and commit all changes. Use conventional commits (`feat:`, `fix:`, `refactor:`, etc.). Never mention Claude/AI in commit messages.
5. **Push** — Push the branch to origin with `-u` flag.
6. **PR** — Create a pull request targeting `master` using `gh pr create`.

## Code Quality

- No magic numbers — numeric literals with domain meaning must be named constants (e.g. `MAX_BODY_LENGTH = 5000`, not bare `5000`)
- No magic strings — repeated string literals used as keys/identifiers must be constants
- Max function length: 30 lines — if longer, decompose
- Max file length: 300 lines — if longer, split into focused modules
- Type hints on all function signatures
- Docstrings on all public classes and methods
- No bare `except Exception:` — catch specific exception types
- No `repo.conn.execute()` outside repository classes — use repository methods
- No business logic in route handlers — use service layer
- No inline HTML string responses — use `render_template()` with partials

## Security Notes

- Scraper validates URLs before fetching (rejects private IPs, non-HTTP schemes, unsafe redirects)
- Template `href` attributes check URL scheme to prevent `javascript:` XSS
- All SQL uses parameterized queries — no string interpolation, no f-strings in SQL
- Scraped content is autoescaped by Jinja2 — never use `|safe` filter on user/scraped data
- Query parameters validated against allowlists (e.g. `sort` param in inbox route)
- JS uses safe DOM methods (`createElement`/`createTextNode`) — never `innerHTML` with dynamic data
- Never expose internal error details to users — log full exception, flash generic message
