"""Flask application factory."""

import logging
import os

from flask import Flask, g, redirect, request, url_for

from jobpilot.config import settings
from jobpilot.gmail.auth import GmailAuth
from jobpilot.storage.database import init_db
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    web_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        static_folder=os.path.join(web_dir, "static"),
        template_folder=os.path.join(web_dir, "templates"),
    )
    app.config["SECRET_KEY"] = settings.secret_key
    app.debug = settings.debug

    # Initialize database and repository
    conn = init_db(settings.db_path)
    repo = Repository(conn)
    app.config["repo"] = repo

    # Classify unprocessed emails and score pending jobs on startup.
    # In debug mode, skip in the reloader parent process to avoid DB lock
    # conflicts — the child (actual server) process will run these.
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _classify_unprocessed(repo)
        _parse_existing_digests(repo)
        _score_pending_jobs(repo)

    # Register routes
    from jobpilot.web.auth_routes import bp_auth
    from jobpilot.web.routes import bp
    app.register_blueprint(bp)
    app.register_blueprint(bp_auth)

    # Auth gate: redirect unauthenticated users to login
    @app.before_request
    def require_auth():
        allowed_prefixes = ("/auth/", "/static/")
        if any(request.path.startswith(p) for p in allowed_prefixes):
            return None
        auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)
        if not auth.is_authenticated():
            return redirect(url_for("auth.login"))
        g.authenticated = True

    # Inject common template variables
    @app.context_processor
    def inject_globals():
        auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)
        authenticated = auth.is_authenticated()
        last_sync = repo.get_last_sync_time() if authenticated else None
        return {"authenticated": authenticated, "last_sync": last_sync}

    return app


def _classify_unprocessed(repo: Repository) -> None:
    """Score and classify any emails that haven't been processed yet."""
    from jobpilot.classifier.rules import RuleBasedScorer, load_signal_config

    config = load_signal_config(repo)
    threshold_str = repo.get_setting("score_threshold")
    threshold = float(threshold_str) if threshold_str else None
    scorer = RuleBasedScorer(config=config, score_threshold=threshold)
    rows = repo.conn.execute(
        "SELECT id, subject, body_text FROM emails WHERE processed = FALSE"
    ).fetchall()

    for row in rows:
        text = row["body_text"] or ""
        result = scorer.score(row["subject"], text)

        ml_score = None
        try:
            from jobpilot.classifier.ml_trainer import MLTrainer
            active_noise = repo.get_active_model("noise")
            if active_noise:
                trainer = MLTrainer(repo)
                preds = trainer.predict_single(
                    "noise", "email", row["id"], row["subject"], text,
                )
                for pred_data in preds.values():
                    if pred_data.get("is_active"):
                        ml_score = pred_data.get("probability")
                        break
        except Exception:
            logger.exception("ML noise prediction failed for %s", row["id"])

        repo.update_email_scores(
            row["id"],
            raw_score=result.score,
            ml_score=ml_score,
            classification=result.classification,
            confidence=result.confidence,
        )


def _parse_existing_digests(repo: Repository) -> None:
    """Parse digest emails that haven't been processed for job extraction yet.

    Also re-parses emails whose extracted jobs have boilerplate titles
    (from before the boilerplate filter was added).
    """
    from jobpilot.gmail.digest import (
        _is_boilerplate_line,
        extract_single_job_url,
        parse_digest,
    )

    already_parsed = repo.get_email_ids_with_extracted_jobs()

    # Find emails with boilerplate titles that need re-parsing
    reparse_email_ids = set()
    boilerplate_rows = repo.conn.execute(
        "SELECT id, email_id, title FROM scraped_jobs WHERE user_label IS NULL"
    ).fetchall()
    for row in boilerplate_rows:
        if row["title"] and _is_boilerplate_line(row["title"]):
            reparse_email_ids.add(row["email_id"])

    # Delete bad jobs and remove from already_parsed so they get re-parsed
    for eid in reparse_email_ids:
        repo.delete_scraped_jobs_for_email(eid)
        already_parsed.discard(eid)

    rows = repo.conn.execute(
        "SELECT * FROM emails WHERE origin_url IS NULL"
    ).fetchall()

    for row in rows:
        email = repo._row_to_email(row)
        if email.id in already_parsed:
            continue

        extracted_jobs = parse_digest(email)
        for job in extracted_jobs:
            repo.insert_scraped_job(job)

        if not extracted_jobs:
            origin_url = extract_single_job_url(email.body_text or "", email.platform)
            if origin_url:
                repo.update_email_origin_url(email.id, origin_url)


def _score_pending_jobs(repo: Repository) -> None:
    """Score scraped jobs that are still pending classification."""
    from jobpilot.classifier.rules import RuleBasedScorer, load_signal_config

    config = load_signal_config(repo)
    threshold_str = repo.get_setting("score_threshold")
    threshold = float(threshold_str) if threshold_str else None
    scorer = RuleBasedScorer(config=config, score_threshold=threshold)
    rows = repo.conn.execute(
        "SELECT id, title, company, location, description"
        " FROM scraped_jobs WHERE classification = 'pending'"
    ).fetchall()

    for row in rows:
        body = (
            f"{row['title']} {row['company'] or ''}"
            f" {row['location'] or ''} {row['description'] or ''}"
        )
        result = scorer.score(row["title"], body)

        ml_score = None
        try:
            from jobpilot.classifier.ml_trainer import MLTrainer
            active_scoring = repo.get_active_model("scoring")
            if active_scoring:
                trainer = MLTrainer(repo)
                preds = trainer.predict_single(
                    "scoring", "scraped_job", str(row["id"]), row["title"], body,
                )
                for pred_data in preds.values():
                    if pred_data.get("is_active"):
                        ml_score = pred_data.get("probability")
                        break
        except Exception:
            logger.exception("ML scoring prediction failed for job %d", row["id"])

        repo.update_scraped_job_scores(
            row["id"], result.score, ml_score, result.classification,
        )
