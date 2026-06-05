"""SQLite database connection and schema management."""

import logging
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from jobpilot.storage.job_repo import DROP_SCORES_SQL

logger = logging.getLogger(__name__)

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
    scrape_attempted BOOLEAN DEFAULT FALSE,
    matched_signals TEXT
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
    status TEXT NOT NULL DEFAULT 'applied' CHECK(status IN (
        'saved', 'applied', 'screening', 'technical',
        'onsite', 'offer', 'accepted', 'rejected',
        'withdrawn', 'no_response'
    )),
    applied_at TEXT DEFAULT (datetime('now')),
    last_status_change TEXT DEFAULT (datetime('now')),
    contact_name TEXT,
    contact_email TEXT,
    notes TEXT,
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


_CLEANUP_BROWSER_SCRAPE_SQL = """
-- Reset corrupted LinkedIn descriptions (login wall content)
UPDATE scraped_jobs
SET description = NULL, scrape_attempted = 0
WHERE (url LIKE 'https://linkedin.com/%' OR url LIKE 'https://%.linkedin.com/%'
       OR url LIKE 'http://linkedin.com/%' OR url LIKE 'http://%.linkedin.com/%')
  AND description IS NOT NULL
  AND (description LIKE '%Sign in to set job alerts%'
       OR description LIKE '%Forgot password%'
       OR description LIKE '%Join now%');

-- Reset failed Glassdoor scrapes for re-attempt
UPDATE scraped_jobs
SET scrape_attempted = 0
WHERE (url LIKE 'https://glassdoor.com/%' OR url LIKE 'https://%.glassdoor.com/%'
       OR url LIKE 'http://glassdoor.com/%' OR url LIKE 'http://%.glassdoor.com/%')
  AND description IS NULL
  AND scrape_attempted = 1;

"""


# Wellfound jobs predating the dedicated HTML parser were extracted by the
# generic text parser and have corrupted fields (titles like "Actively Hiring").
# Deleting the unlabeled ones lets the next sync re-parse the source emails
# correctly. Labeled jobs are preserved — the user already acted on them.
_CLEANUP_WELLFOUND_SQL = (
    "DELETE FROM scraped_jobs "
    "WHERE user_label IS NULL "
    "AND (source = 'wellfound' "
    "     OR url LIKE 'https://wellfound.com/%' "
    "     OR url LIKE 'https://%.wellfound.com/%' "
    "     OR url LIKE 'http://wellfound.com/%' "
    "     OR url LIKE 'http://%.wellfound.com/%')"
)


def _cleanup_corrupted_wellfound_jobs(conn: sqlite3.Connection) -> int:
    """Delete unlabeled Wellfound jobs so they can be re-parsed. Returns count."""
    cursor = conn.execute(_CLEANUP_WELLFOUND_SQL)
    conn.commit()
    return cursor.rowcount


# Glassdoor jobs predating the parsing fixes have corrupted fields (titles eaten
# as salary, hour-durations leaking into location) and duplicate rows from
# per-digest tracking URLs. Deleting the unlabeled ones lets the next sync
# re-parse the source emails with the fixed parser and normalized URLs. Labeled
# jobs are preserved — the user already acted on them — as are any with an
# application attached (deleting them would break the applications FK).
_CLEANUP_GLASSDOOR_SQL = (
    "DELETE FROM scraped_jobs WHERE source = 'glassdoor' AND user_label IS NULL "
    "AND id NOT IN (SELECT scraped_job_id FROM applications "
    "WHERE scraped_job_id IS NOT NULL)"
)


def _cleanup_corrupted_glassdoor_jobs(conn: sqlite3.Connection) -> int:
    """Delete unlabeled Glassdoor jobs so they can be re-parsed. Returns count."""
    cursor = conn.execute(_CLEANUP_GLASSDOOR_SQL)
    conn.commit()
    return cursor.rowcount


# Collapse existing Glassdoor content-duplicates (same posting recurring across
# daily digests with a fresh jobListingId each time). Per (title, company,
# location) group: keep one row — preferring a labeled row (lowest id among them)
# so a user decision is carried over rather than dropped — refresh its link to
# the newest sibling's URL, and delete the rest. In the rare case the same
# posting was labeled differently across digests, only the earliest label is
# kept (one row can hold one label).
#
# Per Glassdoor row: keep_id is its group's survivor (labeled-first, then lowest
# id); fresh_url is the group's newest link (highest id).
_GLASSDOOR_DEDUP_KEYS_SQL = """
SELECT
  id,
  FIRST_VALUE(id) OVER (PARTITION BY k ORDER BY (user_label IS NULL), id) AS keep_id,
  FIRST_VALUE(url) OVER (PARTITION BY k ORDER BY id DESC) AS fresh_url
FROM (
  SELECT id, url, user_label,
         title || '|' || IFNULL(company, '') || '|' || IFNULL(location, '') AS k
  FROM scraped_jobs WHERE source = 'glassdoor'
)
"""


def _dedup_glassdoor_jobs_by_content(conn: sqlite3.Connection) -> int:
    """Collapse Glassdoor content-duplicates to one row each. Returns deleted count.

    For each duplicate row: repoint any applications referencing it to the
    survivor (so the FK holds and the user's application tracking is preserved),
    then delete it. Finally refresh each survivor's link to its freshest sibling
    (done after the deletes so it can't collide with the sibling's UNIQUE url).
    """
    rows = conn.execute(_GLASSDOOR_DEDUP_KEYS_SQL).fetchall()
    survivors: dict[int, str] = {}
    duplicates: list[tuple[int, int]] = []
    for row in rows:
        survivors[row["keep_id"]] = row["fresh_url"]
        if row["id"] != row["keep_id"]:
            duplicates.append((row["id"], row["keep_id"]))
    for dupe_id, keep_id in duplicates:
        conn.execute(
            "UPDATE applications SET scraped_job_id = ? WHERE scraped_job_id = ?",
            (keep_id, dupe_id),
        )
        conn.execute("DELETE FROM scraped_jobs WHERE id = ?", (dupe_id,))
    for keep_id, fresh_url in survivors.items():
        conn.execute(
            "UPDATE scraped_jobs SET url = ? WHERE id = ?", (fresh_url, keep_id)
        )
    conn.commit()
    return len(duplicates)


# Status progression rank — higher means more advanced. Terminal/negative
# outcomes share rank 1 so an "applied"-then-rejected row outranks a bare "saved".
_STATUS_RANK = {
    "saved": 0,
    "applied": 1,
    "screening": 2,
    "technical": 3,
    "onsite": 4,
    "offer": 5,
    "accepted": 6,
    "rejected": 1,
    "withdrawn": 1,
    "no_response": 1,
}

_URL_ALIVE_TIMEOUT = 3.0
_HTTP_ERROR_STATUS = 400
# Cap how many live URL probes the one-time migration may perform so a backlog
# of dead application URLs cannot stall app startup (init_db runs migrations
# synchronously). Beyond the budget, surviving rows keep their original URL.
_MAX_URL_PROBES = 40

# Pull every application with a case-insensitive, NULL-safe content key so
# duplicates collapse into the same group regardless of casing or missing location.
# `created_sort` normalizes mixed timestamp formats so the newest row sorts last.
_DEDUP_APPLICATIONS_SQL = """
SELECT id, scraped_job_id, role_title, company, location, job_url, status, created_at,
       datetime(created_at) AS created_sort,
       LOWER(role_title) || '|' || LOWER(IFNULL(company, '')) || '|' ||
       LOWER(IFNULL(location, '')) AS dedup_key
FROM applications
ORDER BY dedup_key, created_sort
"""


def _is_url_alive(url: str | None, timeout: float = _URL_ALIVE_TIMEOUT) -> bool:
    """Return True if url is safe to fetch and responds with a 2xx/3xx status."""
    from jobpilot.scraper.job_page import is_safe_url  # local import keeps storage light

    if not url or not is_safe_url(url):
        return False
    try:
        resp = urllib.request.urlopen(
            urllib.request.Request(url, method="HEAD"), timeout=timeout
        )
        return resp.status < _HTTP_ERROR_STATUS
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _pick_survivor(members: list[sqlite3.Row]) -> sqlite3.Row:
    """Choose the survivor: most-advanced status, then newest created_at."""
    return max(
        members,
        key=lambda r: (_STATUS_RANK.get(r["status"], 0), r["created_sort"] or ""),
    )


def _resolve_survivor_url(
    conn: sqlite3.Connection, survivor: sqlite3.Row, duplicates: list[sqlite3.Row]
) -> int:
    """Swap a dead survivor URL for the first reachable duplicate's URL.

    Returns the number of liveness probes performed so the caller can bound
    total network I/O across the one-time migration.
    """
    if _is_url_alive(survivor["job_url"]):
        return 1
    probes = 1
    for dupe in duplicates:
        probes += 1
        if _is_url_alive(dupe["job_url"]):
            conn.execute(
                "UPDATE applications SET job_url = ? WHERE id = ?",
                (dupe["job_url"], survivor["id"]),
            )
            break
    return probes


def _delete_orphaned_scraped_job(conn: sqlite3.Connection, scraped_job_id: int | None) -> None:
    """Delete a scraped_job row if no remaining application references it."""
    if scraped_job_id is None:
        return
    still_used = conn.execute(
        "SELECT 1 FROM applications WHERE scraped_job_id = ? LIMIT 1", (scraped_job_id,)
    ).fetchone()
    if not still_used:
        conn.execute("DELETE FROM scraped_jobs WHERE id = ?", (scraped_job_id,))


def _collapse_duplicates(
    conn: sqlite3.Connection, survivor: sqlite3.Row, duplicates: list[sqlite3.Row]
) -> None:
    """Reroute history to the survivor, delete duplicates, clean orphaned scraped_jobs."""
    for dupe in duplicates:
        conn.execute(
            "UPDATE application_status_history SET application_id = ? WHERE application_id = ?",
            (survivor["id"], dupe["id"]),
        )
        conn.execute("DELETE FROM applications WHERE id = ?", (dupe["id"],))
        _delete_orphaned_scraped_job(conn, dupe["scraped_job_id"])


def _dedup_tracked_applications(conn: sqlite3.Connection) -> int:
    """Collapse applications duplicated by (title, company, location). Returns count removed."""
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in conn.execute(_DEDUP_APPLICATIONS_SQL).fetchall():
        groups.setdefault(row["dedup_key"], []).append(row)
    removed = 0
    probes = 0
    for members in groups.values():
        if len(members) <= 1:
            continue
        survivor = _pick_survivor(members)
        duplicates = [m for m in members if m["id"] != survivor["id"]]
        if probes < _MAX_URL_PROBES:
            probes += _resolve_survivor_url(conn, survivor, duplicates)
        _collapse_duplicates(conn, survivor, duplicates)
        removed += len(duplicates)
    conn.commit()
    logger.info("Deduplicated %d tracked application(s)", removed)
    return removed


def _run_once(
    conn: sqlite3.Connection,
    key: str,
    action: Callable[[sqlite3.Connection], object],
) -> None:
    """Run a one-time data migration `action` unless its `key` is already set.

    Records the key in `settings` afterwards so the action never runs twice.
    """
    try:
        ran = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.OperationalError:
        ran = None
    if ran:
        return
    action(conn)
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, "1")
    )
    conn.commit()


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    """Add columns and run the idempotent schema scripts."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(model_versions)").fetchall()}
    if "model_type" not in existing:
        conn.execute("ALTER TABLE model_versions ADD COLUMN model_type TEXT DEFAULT 'scoring'")
    if "algorithm" not in existing:
        conn.execute("ALTER TABLE model_versions ADD COLUMN algorithm TEXT DEFAULT 'LR'")
    if "train_accuracy" not in existing:
        conn.execute("ALTER TABLE model_versions ADD COLUMN train_accuracy REAL")
    conn.executescript(MIGRATION_SQL)
    conn.executescript(MIGRATION_PREFS_SQL)

    app_cols = {row[1] for row in conn.execute("PRAGMA table_info(applications)").fetchall()}
    if "remote" not in app_cols:
        conn.execute("ALTER TABLE applications ADD COLUMN remote BOOLEAN DEFAULT FALSE")
        conn.execute(
            """UPDATE applications SET remote = (
                SELECT sj.remote FROM scraped_jobs sj
                WHERE sj.id = applications.scraped_job_id
            ) WHERE scraped_job_id IS NOT NULL"""
        )
        conn.commit()


def _cleanup_browser_scrape(conn: sqlite3.Connection) -> None:
    """Reset corrupted login-wall descriptions and failed scrapes for re-attempt."""
    for stmt in _CLEANUP_BROWSER_SCRAPE_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


def _migrate_job_title_tiers(conn: sqlite3.Connection) -> None:
    """Rename the job_title preference category and drop scores for a rescore."""
    conn.execute(
        "UPDATE user_preferences SET category = 'job_title_primary' "
        "WHERE category = 'job_title'"
    )
    conn.execute(DROP_SCORES_SQL)


def _retry_glassdoor_browser(conn: sqlite3.Connection) -> None:
    """Re-arm failed Glassdoor scrapes after switching to the browser strategy."""
    conn.execute(
        "UPDATE scraped_jobs SET scrape_attempted = 0 "
        "WHERE (url LIKE 'https://glassdoor.com/%' "
        "       OR url LIKE 'https://%.glassdoor.com/%' "
        "       OR url LIKE 'http://glassdoor.com/%' "
        "       OR url LIKE 'http://%.glassdoor.com/%') "
        "  AND description IS NULL "
        "  AND scrape_attempted = 1"
    )


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply incremental schema changes and one-time data migrations idempotently."""
    _apply_column_migrations(conn)
    _run_once(conn, "_migration_browser_scrape_cleanup", _cleanup_browser_scrape)
    _run_once(conn, "_migration_job_title_tiers", _migrate_job_title_tiers)
    _run_once(conn, "_migration_glassdoor_browser_retry", _retry_glassdoor_browser)
    _run_once(conn, "_migration_wellfound_cleanup", _cleanup_corrupted_wellfound_jobs)
    _run_once(conn, "_migration_glassdoor_parsing_cleanup", _cleanup_corrupted_glassdoor_jobs)
    _run_once(conn, "_migration_glassdoor_content_dedup", _dedup_glassdoor_jobs_by_content)
    _run_once(conn, "_migration_dedup_tracked_applications", _dedup_tracked_applications)


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
    for title, info in TARGET_JOB_TITLES.items():
        cat = info.get("category", "secondary")
        if cat == "primary":
            rows.append(("job_title_primary", title, None))
        else:
            rows.append(("job_title_secondary", title, None))

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
