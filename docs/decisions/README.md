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
