"""Schema and data migrations for non-job email detection.

Kept out of migrations.py, which is already long, and grouped here because the
three steps only make sense together: the column, the re-evaluation that fills
it, and the narrowing of the Gmail query that stopped producing the mail it
rejects.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

_GOOGLE_DOMAIN_PREF = "google.com"

# Feedback labels that assert the email IS a job. A human decision outranks a
# pattern, so a row carrying one of these is never re-evaluated — the rule would
# be contradicting a person who looked at the same email and disagreed.
#
# 'not_a_job' is deliberately absent, and that is not the two concepts merging:
# the label is never read as evidence, only as a veto, and a rule still has to
# match the subject on its own to reject anything. Vetoing on agreement would
# leave the hand-confirmed noise flagged job-related, which is the corpus defect
# this migration exists to correct.
_LABELS_ASSERTING_JOB = ("worth_checking", "skip")

# Re-evaluation candidates: every stored email except those a human said is a job.
# num_jobs mirrors what the detector saw at fetch time, so a digest that yielded
# jobs still outranks any rejection rule.
# The placeholder count here must match len(_LABELS_ASSERTING_JOB). The SQL is
# written out rather than built by interpolation — CLAUDE.md allows no f-strings
# in SQL — so test_placeholder_count_matches_the_label_tuple guards the pairing.
_REEVALUATE_SQL = """
SELECT e.id, e.subject, e.sender, e.platform,
       (SELECT COUNT(*) FROM scraped_jobs s WHERE s.email_id = e.id) AS num_jobs
FROM emails e
WHERE e.id NOT IN (
    SELECT email_id FROM user_feedback WHERE label IN (?, ?)
)
"""


def add_non_job_rule_column(conn: sqlite3.Connection) -> None:
    """Add emails.non_job_rule, the name of the rule that rejected an email.

    Nothing is backfilled here: reevaluate_non_job_emails fills it. NULL means
    the email was never rejected, or was rejected before the column existed.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(emails)").fetchall()}
    if "non_job_rule" in cols:
        return
    conn.execute("ALTER TABLE emails ADD COLUMN non_job_rule TEXT")
    conn.commit()


def reevaluate_non_job_emails(conn: sqlite3.Connection) -> int:
    """Re-run non-job detection over stored emails. Returns rows rejected.

    Only ever flips job-related to not-job-related. A row already at 0 keeps that
    value and gains its rule; nothing is promoted back to job-related, because the
    old LinkedIn check rejected mail these rules do not all reproduce.

    Rows a human labelled 'worth_checking' or 'skip' are left alone entirely — see
    _LABELS_ASSERTING_JOB.
    """
    from jobpilot.classifier.job_detector import JobDetector

    detector = JobDetector()
    rejected = 0
    for row in conn.execute(_REEVALUATE_SQL, _LABELS_ASSERTING_JOB).fetchall():
        verdict = detector.classify(
            row["subject"], row["sender"], row["platform"],
            None, row["num_jobs"],
        )
        if verdict.is_job:
            continue
        conn.execute(
            "UPDATE emails SET is_job_related = FALSE, non_job_rule = ? WHERE id = ?",
            (verdict.non_job_rule, row["id"]),
        )
        rejected += 1
    conn.commit()
    logger.info("Re-evaluated stored emails: %d now not job-related", rejected)
    return rejected


def narrow_google_alerts_domain(conn: sqlite3.Connection) -> None:
    """Replace the google.com monitored domain with the Google Alerts sender.

    The domain was monitored for Google Alerts job alerts; it also matched every
    Gmail account notice. Narrowing keeps the job alerts and stops the noise at
    the query, rather than fetching it only to reject it.
    """
    from jobpilot.gmail.fetcher import GOOGLE_ALERTS_SENDER  # keeps storage light

    present = conn.execute(
        "SELECT 1 FROM user_preferences WHERE category = 'monitored_domain'"
        " AND value = ?",
        (_GOOGLE_DOMAIN_PREF,),
    ).fetchone()
    if not present:
        return
    conn.execute(
        "INSERT OR IGNORE INTO user_preferences (category, value, extra)"
        " VALUES ('monitored_domain', ?, NULL)",
        (GOOGLE_ALERTS_SENDER,),
    )
    conn.execute(
        "DELETE FROM user_preferences WHERE category = 'monitored_domain'"
        " AND value = ?",
        (_GOOGLE_DOMAIN_PREF,),
    )
    conn.commit()
