# ADR-012: Pydantic Settings for configuration

**Status:** accepted
**Date:** 2026-05-07
**Tags:** infrastructure, config

## Context

JobPilot has many tunable settings spread across concerns: file paths (DB, Gmail
credentials/token), server host/port/secret/debug, logging, ML thresholds
(`score_threshold`, `min_training_samples`, …), scoring weights, and scheduler
timings. These need sensible defaults so the app runs out of the box, must be
overridable per environment (e.g. a custom DB path or port), and should be
type-checked and available app-wide from one place — not read ad hoc from
`os.environ` scattered through the code.

## Decision

Use **pydantic-settings** (`BaseSettings`) for a single typed configuration object
in `config.py`.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JOBPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
    )
    db_path: Path = Path.home() / ".jobpilot" / "jobpilot.db"
    # ... server, logging, ML thresholds, scoring weights, scheduler ...

settings = Settings()
```

- Every field has a typed default; Pydantic coerces env-var strings to the right type.
- Overridable via `JOBPILOT_`-prefixed environment variables or a `.env` file.
- The Flask secret key is generated once and persisted to `~/.jobpilot/.secret_key`.
- A single module-level `settings` instance is imported wherever config is needed.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Raw `os.environ` reads | No types, no validation, no defaults in one place; config logic scatters across modules. |
| `configparser` / INI / YAML file | Manual parsing and type coercion; no env-var overlay; more boilerplate. |
| `python-dotenv` alone | Loads `.env` but gives no typed schema, defaults, or validation. |

## Consequences

### Positive
- One typed, validated, IDE-friendly source of truth for all settings.
- Env-var + `.env` overrides with automatic type coercion.
- Sensible defaults mean zero-config first run.

### Negative / Tradeoffs
- Adds `pydantic-settings` as a dependency.
- The module-level singleton is read at import time, which can complicate test isolation.

### Risks
- Pydantic v2/settings API changes could require config migration.

## Related

- ADRs: [ADR-002](002-sqlite-wal.md) (DB path), [ADR-008](008-scikit-learn-ml.md) (ML thresholds/weights live here)
- Code: `src/jobpilot/config.py`
- Commits: `283f9b8` (initial Settings class)

> Note: the explicit reason for choosing pydantic-settings over alternatives was not
> recorded; this ADR documents the resulting configuration approach.
