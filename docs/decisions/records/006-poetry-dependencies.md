# ADR-006: Poetry for dependencies

**Status:** accepted
**Date:** 2026-05-07
**Tags:** infrastructure

## Context

JobPilot has a non-trivial dependency set (Flask, Google API client + OAuth libs,
scikit-learn, Playwright, APScheduler, Pydantic Settings, BeautifulSoup/lxml) plus
dev tooling (pytest, ruff) and a CLI entry point. We needed reproducible installs,
a single source of truth for dependencies and dev-dependencies, and a defined
console-script entry point — without hand-maintaining `requirements.txt` and
`setup.py` separately.

## Decision

Use **Poetry** for dependency management and packaging, configured in
`pyproject.toml`:

- Project metadata, runtime dependencies, and a `[tool.poetry.group.dev]` block for
  dev-only tools (pytest, ruff).
- Python constraint `^3.11`.
- Console entry point `jobpilot = "jobpilot.cli:cli"`.
- `tool.ruff` config (selected rule sets, target `py311`, line length) co-located in
  the same file.

All documented commands run through Poetry (`poetry run pytest`, `poetry run ruff check`).

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| pip + `requirements.txt` | No lockfile by default, no dev/runtime split, separate packaging config needed. |
| Pipenv | Largely superseded by Poetry; slower resolver, weaker packaging story. |
| Conda | Heavyweight; oriented at scientific environment management rather than app packaging. |

## Consequences

### Positive
- Single `pyproject.toml` for deps, dev-deps, tool config, and entry points.
- Lockfile gives reproducible installs.
- Clean separation of runtime vs dev dependencies.

### Negative / Tradeoffs
- Contributors must have Poetry installed (extra onboarding step over plain pip).

### Risks
- Poetry/PEP 621 metadata conventions evolve; future Poetry versions may require config migration.

## Related

- ADRs: [ADR-008](008-scikit-learn-ml.md), [ADR-001](001-playwright-scraping.md) (dependencies managed here)
- Code: `pyproject.toml`
- Docs: `CLAUDE.md` (Commands)

> Note: an explicit rationale for choosing Poetry over pip/Pipenv was not recorded;
> this ADR documents the resulting setup and the standard tradeoffs.
