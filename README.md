# JobPilot

Local job search autopilot — monitors Gmail for job alerts, parses digests, scores listings, and learns your preferences.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask 3](https://img.shields.io/badge/Flask-3-000000?logo=flask)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite)](https://www.sqlite.org/)
[![htmx 2.0](https://img.shields.io/badge/htmx-2.0-3366CC)](https://htmx.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Screenshots

<!-- Screenshots pending — save images to docs/screenshots/ and they will render below -->

![Inbox view with job cards, scores, and signal pills](docs/screenshots/inbox.png)

![Expanded job card with description and signal highlights](docs/screenshots/expanded.png)

![Stats dashboard with charts](docs/screenshots/stats.png)

![Settings page with preferences](docs/screenshots/settings.png)

## Features

- **Gmail monitoring with OAuth** — fetches job alert emails automatically
- **Digest parsing** — splits LinkedIn/Indeed/Wellfound digest emails into individual job cards
- **Rule-based scoring** — configurable signals (tech stack, location, seniority, salary, negatives)
- **ML classification** — trains scikit-learn models (LR, RF, GBC, SVM) from user labels
- **Job page scraping** — fetches full descriptions for ambiguous scores, re-scores with full text
- **Signal highlighting** — matched keywords highlighted green (positive) / red (negative) in descriptions
- **Stats dashboard** — Chart.js visualizations of sources, scores, labels, and ML readiness
- **Dark theme** — full light/dark mode with system preference detection
- **ArbeitNow integration** — additional job source via API

## How It Works

```
Gmail API → Fetch alerts → Parse digests → Extract signals
    → Score & classify (rules + ML) → Review inbox
    → Label jobs (worth_checking / skip) → Train ML models
```

JobPilot uses a feedback loop: you review and label jobs as "worth checking" or "skip", and the ML models learn from your decisions. As you label more jobs, predictions improve — the system adapts to your preferences over time.

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.11+, Flask 3, Pydantic Settings |
| **Frontend** | Jinja2, htmx 2.0, Pico CSS v2, Chart.js |
| **Database** | SQLite with WAL mode |
| **ML** | scikit-learn (Logistic Regression, Random Forest, Gradient Boosting, SVM) |
| **Auth** | Google OAuth 2.0 (Gmail API) |
| **Package manager** | Poetry |

## Architecture

| Module | Purpose |
|--------|---------|
| `web/` | Flask routes + Jinja2 templates |
| `services/` | Business logic layer |
| `repositories/` | SQLite data access |
| `classifier/` | Signal extraction, feature scoring, rule engine, ML models |
| `gmail/` | Gmail API client, email parser, digest splitter |
| `scraper/` | Job page scraper, ArbeitNow API client |

## Getting Started

```bash
# Prerequisites: Python 3.11+, Poetry

# 1. Clone and install
git clone https://github.com/idle-dt/jobpilot.git
cd jobpilot
poetry install

# 2. Google credentials
# Create a Google Cloud project, enable Gmail API,
# download OAuth credentials as credentials.json to project root

# 3. Run
PYTHONPATH=src python -m jobpilot serve
# Open http://localhost:5050
```

## License

[MIT](LICENSE)
