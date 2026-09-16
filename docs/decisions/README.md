# Architecture Decision Records

Decisions that shaped JobPilot's architecture, technology choices, and design patterns.
Each ADR explains *what* was decided, *why*, and *what alternatives were rejected*.

The decision records live in [`records/`](records/). The template for new ADRs is
[`TEMPLATE.md`](TEMPLATE.md).

## How to Use

- **Adding a platform/integration?** Search tags for `scraping`, `api`, `integration`
- **Upgrading a component?** Find its ADR to understand the original problem it solved
- **New contributor?** Read ADRs in order for a project history walkthrough

## Index

| # | Decision | Status | Tags |
|---|----------|--------|------|
| 001 | [Playwright for job page scraping](records/001-playwright-scraping.md) | accepted | scraping, browser |
| 002 | [SQLite with WAL mode](records/002-sqlite-wal.md) | accepted | database, storage |
| 003 | [Flask + Jinja2 + htmx](records/003-flask-jinja2-htmx.md) | accepted | frontend, backend |
| 004 | [Rule-based scoring + optional ML](records/004-rule-based-plus-ml.md) | accepted | ml, classification |
| 005 | [Pico CSS with custom theme](records/005-pico-css-theme.md) | accepted | frontend, design |
| 006 | [Poetry for dependencies](records/006-poetry-dependencies.md) | accepted | infrastructure |
| 007 | [Gmail API for email access](records/007-gmail-api.md) | accepted | integration, email |
| 008 | [scikit-learn for ML models](records/008-scikit-learn-ml.md) | accepted | ml, classification |
| 009 | [Persistent browser profiles](records/009-persistent-browser-profiles.md) | accepted | scraping, browser |
| 010 | [Spec-driven development workflow](records/010-spec-driven-development.md) | accepted | process, workflow |
| 011 | [Digest parsing for multi-job emails](records/011-digest-parsing.md) | accepted | email, parsing |
| 012 | [Pydantic Settings for configuration](records/012-pydantic-settings.md) | accepted | infrastructure, config |
| 013 | [Per-platform email parsing and scraping strategy](records/013-per-platform-parsing-scraping.md) | accepted | scraping, email, parsing, integration |
| 014 | [Plain-HTTP OAuth permitted on loopback only](records/014-loopback-oauth-transport.md) | accepted | security, integration, config |
| 015 | [Wait out the Gmail quota; "Synced" means every message handled](records/015-gmail-quota-waiting.md) | accepted | integration, email, reliability |
| 016 | [Scoring features read user preferences; noise features stay hardcoded](records/016-split-feature-basis.md) | accepted | ml, classification, storage |
| 017 | [Machine-authored labels share the label column, tagged by provenance](records/017-label-provenance-and-training-gate.md) | accepted | ml, classification, storage, process |
| 018 | [Hand-backs and the rejection record](records/018-hand-back-and-rejection-record.md) | accepted | ml, database, labeling |
