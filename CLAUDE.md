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

- `scripts/test_summary.sh` — run all tests, failures only, output capped at 60 lines
- `poetry run pytest tests/` — run all tests (full output)
- `PYTHONPATH=src python -m jobpilot serve` — run dev server on :5050
- `poetry run ruff check src/` — lint

## Architecture

- **Routes** (`web/routes.py`) -> **Services** (`services/`) -> **Repositories** (`repositories/`)
- Classifier pipeline: `signals.py` (keyword definitions) -> `features.py` (score functions) -> `rules.py` (weighted scorer)
- Gmail pipeline: `fetcher.py` (API calls) -> `parser.py` (extract fields) -> `digest.py` (split digests into individual jobs)
- Scraper: `job_page.py` (generic page scraper) + `arbeitnow.py` (API integration)
- ML: `ml_training.py` (train scikit-learn models) + `ml_prediction.py` (predict with trained models)

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

## Writing Specs

When creating a new spec, copy `docs/specs/SPEC_TEMPLATE.md` to `docs/specs/SPEC_<name>.md` and fill it in. Guidelines:

- **Problem** must explain *why*, not just *what* — a reader should understand the motivation without context.
- **Requirements** table: brief, each row is one testable requirement.
- **Implementation Steps**: code snippets are encouraged but keep them focused on the change, not the entire function.
- **Verification > Logic Verification** is the most important section. Each item must be a concrete scenario with an expected value: "input X produces output Y". Avoid vague checks like "verify it works correctly".
- **Implementation Report** is filled in when the work is complete, not when writing the spec.
- Add the spec to `docs/TODO.md` under "In Progress" when created.

## Architecture Decision Records

- **`docs/decisions/`** — Records of key architecture and technology decisions with rationale.
- **`docs/decisions/README.md`** — Index of all ADRs.
- **`docs/decisions/TEMPLATE.md`** — Template for new ADRs.
- **`docs/decisions/records/`** — The individual ADR files (`NNN-slug.md`).

### When to Create an ADR

- Introducing a new technology, library, or external service
- Choosing between two or more viable approaches
- Changing or replacing an existing component
- Making a design decision that would surprise a future reader

### When to Update an ADR

- The decision is superseded — update status to `superseded by [ADR-NNN]`, create the new ADR
- New consequences discovered — append to Consequences section
- Alternatives landscape changed — add new entries to Alternatives table

### ADR Rules

- One decision per file, numbered sequentially (`NNN-slug.md`) in `docs/decisions/records/`
- Use the template at `docs/decisions/TEMPLATE.md`
- Add tags for searchability
- Cross-reference related ADRs, specs, and code paths
- If rationale is unknown, write `(rationale not recorded)` — don't guess

## /ship Command

When the user says `/ship`, execute this flow in order. Stop and report if any step fails.

1. **Test** — Run `scripts/test_summary.sh` and `poetry run ruff check src/`. If either fails, stop.
2. **Verify logic** — Run the Logic Verification checklist from the spec's Verification section. Each scenario must produce the expected result. If any check fails, stop and fix.
3. **Audit** — Spawn the `diff-auditor` agent to audit the changes against the Code Rules below. Paste the full `git diff` into the agent's prompt rather than having it open each changed file itself — the diff is already in hand, and re-reading it costs ~20 tool calls per review. Still tell it to search and read freely for anything the diff alone can't answer (call sites of a changed signature, whether a referenced symbol is in scope). Report findings with severity. Block on HIGH/CRITICAL — prompt to fix. MEDIUM issues are reported but don't block.
4. **Branch** — Create branch from HEAD. Naming: `feat/`, `fix/`, `refactor/` + spec name. One spec = one branch.
5. **Commit** — Conventional commits (`feat:`, `fix:`, `refactor:`). Never mention Claude/AI.
6. **Push** — Push with `-u` flag.
7. **PR** — `gh pr create` targeting `master`.
8. **Update tracker** — In `docs/TODO.md`, remove the spec entry from "In Progress".
9. **Delete spec file** — Ask the user for confirmation, then remove the implemented `docs/specs/SPEC_*.md` file.
10. **ADR check** — If the work introduced a new technology, replaced a component, or made a significant architectural choice, ask whether it warrants an Architecture Decision Record. If yes, create the ADR in `docs/decisions/records/` from the template, update `docs/decisions/README.md`, commit with a `docs:` prefix, and push to the same branch.

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
