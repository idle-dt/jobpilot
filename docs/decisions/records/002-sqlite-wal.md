# ADR-002: SQLite with WAL mode

**Status:** accepted
**Date:** 2026-05-07
**Tags:** database, storage

## Context

JobPilot is a local, single-user job-search autopilot. It needs durable storage
for emails, extracted signals, user feedback, ML model versions, scraped jobs,
and applications — but it runs on the user's own machine, not a server, so a
standalone database service would be overkill. A background scheduler (email
fetch / scrape jobs) can write while the Flask web UI reads concurrently, so the
store has to tolerate a reader and a writer at the same time without locking up.

## Decision

Use SQLite as the single embedded datastore, with these pragmas applied on every
connection in `get_connection()`:

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
conn.execute("PRAGMA foreign_keys=ON")
```

- **WAL (Write-Ahead Logging)** lets readers and a writer proceed concurrently
  instead of blocking each other (the classic SQLite reader/writer lock problem).
- **`busy_timeout=5000`** waits up to 5s for a lock instead of failing immediately.
- **`foreign_keys=ON`** enforces referential integrity (off by default in SQLite).

Connections use `check_same_thread=False` and a `sqlite3.Row` row factory. The DB
path defaults to `~/.jobpilot/jobpilot.db` (configurable — see [ADR-012](012-pydantic-settings.md)).

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| PostgreSQL / MySQL | Requires running a separate server; far too heavy for a single-user local tool. |
| SQLite in default rollback-journal mode | Writer blocks readers; the scheduler writing during a UI read would stall the page. WAL solves this. |
| Flat files / JSON | No transactions, no indexes, no relational integrity for the multi-table schema. |

## Consequences

### Positive
- Zero-config, single-file database that ships with Python — no service to install.
- WAL allows the background scheduler and web UI to read/write concurrently.
- Foreign keys + indexes keep the relational schema consistent and queryable.

### Negative / Tradeoffs
- Not suited to multi-machine or high-concurrency multi-writer use.
- WAL leaves auxiliary `-wal`/`-shm` files alongside the database.

### Risks
- Heavy long-running write transactions could still hit the busy timeout under load.

## Related

- ADRs: [ADR-012](012-pydantic-settings.md) (DB path configuration)
- Code: `src/jobpilot/storage/database.py`, `src/jobpilot/config.py`
- Commits: `283f9b8` (initial schema and WAL configuration)

> Note: the choice of WAL specifically is inferred from the pragmas and the
> concurrent-access design; an explicit written rationale was not recorded at the
> time the schema was created.
