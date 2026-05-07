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
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create a database connection with WAL mode and foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize the database with schema, return connection."""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
