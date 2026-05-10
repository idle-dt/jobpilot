"""SQLite database connection and schema management."""

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    sender_domain TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_text TEXT,
    body_html TEXT,
    received_at TIMESTAMP NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    platform TEXT,
    is_job_related BOOLEAN DEFAULT TRUE,
    raw_score REAL,
    ml_score REAL,
    final_classification TEXT,
    confidence REAL,
    processed BOOLEAN DEFAULT FALSE,
    origin_url TEXT
);

CREATE TABLE IF NOT EXISTS extracted_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL REFERENCES emails(id),
    signal_type TEXT NOT NULL,
    signal_value TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL REFERENCES emails(id),
    label TEXT NOT NULL,
    feedback_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    training_samples INTEGER NOT NULL,
    accuracy REAL,
    precision_score REAL,
    recall_score REAL,
    f1_score REAL,
    model_blob BLOB NOT NULL,
    feature_names TEXT,
    is_active BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS platform_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_name TEXT NOT NULL,
    sender_pattern TEXT,
    subject_pattern TEXT,
    domain_pattern TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS scraped_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    url TEXT NOT NULL UNIQUE,
    salary TEXT,
    posted_date TEXT,
    remote BOOLEAN DEFAULT FALSE,
    scraped_at TEXT DEFAULT (datetime('now')),
    score REAL,
    ml_score REAL,
    classification TEXT DEFAULT 'pending',
    user_label TEXT,
    labeled_at TEXT,
    email_id TEXT REFERENCES emails(id),
    expired BOOLEAN DEFAULT FALSE,
    description TEXT,
    scrape_attempted BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT REFERENCES emails(id),
    scraped_job_id INTEGER REFERENCES scraped_jobs(id),
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    location TEXT,
    salary_range TEXT,
    job_url TEXT,
    platform TEXT,
    track TEXT CHECK(track IN ('A', 'B')),
    status TEXT NOT NULL DEFAULT 'applied' CHECK(status IN (
        'saved', 'applied', 'screening', 'technical',
        'onsite', 'offer', 'accepted', 'rejected',
        'withdrawn', 'no_response'
    )),
    saved_at TEXT,
    applied_at TEXT DEFAULT (datetime('now')),
    last_status_change TEXT DEFAULT (datetime('now')),
    contact_name TEXT,
    contact_email TEXT,
    notes TEXT,
    cover_letter_track TEXT,
    cv_version TEXT,
    offer_salary TEXT,
    offer_currency TEXT,
    offer_equity TEXT,
    offer_relocation_package TEXT,
    offer_notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS application_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    changed_at TEXT DEFAULT (datetime('now')),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    value TEXT NOT NULL,
    extra TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, value)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_platform ON emails(platform);
CREATE INDEX IF NOT EXISTS idx_emails_classification ON emails(final_classification);
CREATE INDEX IF NOT EXISTS idx_feedback_email ON user_feedback(email_id);
CREATE INDEX IF NOT EXISTS idx_signals_email ON extracted_signals(email_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_scraped_url ON scraped_jobs(url);
CREATE INDEX IF NOT EXISTS idx_scraped_class ON scraped_jobs(classification);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_company ON applications(company);
CREATE INDEX IF NOT EXISTS idx_applications_track ON applications(track);
CREATE INDEX IF NOT EXISTS idx_applications_email ON applications(email_id);
CREATE INDEX IF NOT EXISTS idx_applications_scraped ON applications(scraped_job_id);
CREATE INDEX IF NOT EXISTS idx_scraped_email ON scraped_jobs(email_id);
CREATE INDEX IF NOT EXISTS idx_status_history_app ON application_status_history(application_id);
CREATE INDEX IF NOT EXISTS idx_prefs_category ON user_preferences(category);
"""

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS ml_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version_id INTEGER NOT NULL REFERENCES model_versions(id),
    item_type TEXT NOT NULL CHECK(item_type IN ('email', 'scraped_job')),
    item_id TEXT NOT NULL,
    prediction TEXT NOT NULL,
    probability REAL,
    predicted_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ml_pred_item ON ml_predictions(item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_ml_pred_model ON ml_predictions(model_version_id);
"""


MIGRATION_PREFS_SQL = """
CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    value TEXT NOT NULL,
    extra TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, value)
);
CREATE INDEX IF NOT EXISTS idx_prefs_category ON user_preferences(category);
"""


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply incremental schema changes idempotently."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(model_versions)").fetchall()}
    if "model_type" not in existing:
        conn.execute("ALTER TABLE model_versions ADD COLUMN model_type TEXT DEFAULT 'scoring'")
    if "algorithm" not in existing:
        conn.execute("ALTER TABLE model_versions ADD COLUMN algorithm TEXT DEFAULT 'LR'")
    if "train_accuracy" not in existing:
        conn.execute("ALTER TABLE model_versions ADD COLUMN train_accuracy REAL")
    conn.executescript(MIGRATION_SQL)
    conn.executescript(MIGRATION_PREFS_SQL)


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create a database connection with WAL mode and foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _seed_default_preferences(conn: sqlite3.Connection) -> None:
    """Seed user_preferences with hardcoded defaults on first run."""
    count = conn.execute("SELECT COUNT(*) as cnt FROM user_preferences").fetchone()[0]
    if count > 0:
        return

    from jobpilot.classifier.signals import (
        LOCATION_PATTERNS,
        NEGATIVE_SIGNALS,
        SENIORITY_PATTERNS,
        TARGET_JOB_TITLES,
        TECH_STACK_KEYWORDS,
    )
    from jobpilot.gmail.fetcher import MONITORED_DOMAINS

    rows = []

    # Tech keywords
    for keyword, info in TECH_STACK_KEYWORDS.items():
        cat = info.get("category", "secondary")
        if cat == "primary":
            rows.append(("tech_keyword_primary", keyword, None))
        else:
            rows.append(("tech_keyword_secondary", keyword, None))

    # Job titles
    for title in TARGET_JOB_TITLES:
        rows.append(("job_title", title, None))

    # Seniority
    for pattern, info in SENIORITY_PATTERNS.items():
        if info["weight"] > 0:
            rows.append(("seniority_wanted", pattern, None))
        else:
            rows.append(("seniority_unwanted", pattern, None))

    # Locations
    for location, info in LOCATION_PATTERNS.items():
        if info["weight"] < 0:
            rows.append(("location_negative", location, None))
        elif info.get("target"):
            rows.append(("location_primary", location, None))
        else:
            rows.append(("location_secondary", location, None))

    # Negative signals
    for signal in NEGATIVE_SIGNALS:
        rows.append(("negative_signal", signal, None))

    # Monitored domains
    for domain in MONITORED_DOMAINS:
        rows.append(("monitored_domain", domain, None))

    conn.executemany(
        "INSERT OR IGNORE INTO user_preferences (category, value, extra) VALUES (?, ?, ?)",
        rows,
    )

    # Seed default settings
    defaults = [
        ("salary_currency", "EUR"),
        ("salary_min", "60000"),
        ("salary_max", ""),
        ("score_threshold", "0.6"),
        ("arbeitnow_enabled", "true"),
        ("arbeitnow_visa_only", "false"),
    ]
    for key, value in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    conn.commit()


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize the database with schema, return connection."""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    _run_migrations(conn)
    _seed_default_preferences(conn)
    conn.commit()
    return conn
