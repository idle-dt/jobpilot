"""Route handlers for the web UI."""

import logging
import time

from flask import Blueprint, current_app, jsonify, render_template, request

from jobpilot.config import settings
from jobpilot.storage.models import UserFeedback

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)

SIGNAL_PRIORITY = {
    "tech_stack": 0,
    "location": 1,
    "salary": 2,
    "job_title": 3,
    "seniority": 4,
    "negative": 5,
    "platform": 6,
}


def _sort_signals(signals: list) -> list:
    return sorted(signals, key=lambda s: SIGNAL_PRIORITY.get(s.signal_type, 99))


def _get_param(name: str, default: str = "") -> str:
    """Get a parameter from form data or JSON body, safely."""
    val = request.form.get(name)
    if val:
        return val
    try:
        return (request.json or {}).get(name, default)
    except Exception:
        return default


def _repo():
    return current_app.config["repo"]


@bp.route("/")
def inbox():
    """Review queue — emails needing user feedback."""
    repo = _repo()
    _VALID_SORTS = {"score_desc", "score_asc", "date_desc", "date_asc"}
    sort = request.args.get("sort", "score_desc")
    if sort not in _VALID_SORTS:
        sort = "score_desc"
    emails = repo.get_emails_for_review(limit=50)

    # Also get scraped jobs for review
    scraped = repo.get_scraped_jobs_for_review(limit=50)

    # Filter out emails whose jobs were extracted into scraped_jobs
    digested_ids = repo.get_email_ids_with_extracted_jobs()
    emails = [e for e in emails if e.id not in digested_ids]

    # Attach signals to each email, sorted by priority
    for email in emails:
        email.signals = _sort_signals(repo.get_signals_for_email(email.id))

    # Build unified list for sorting
    items = []
    for email in emails:
        items.append({
            "type": "email",
            "obj": email,
            "score": email.raw_score or 0,
            "date": email.received_at.isoformat() if email.received_at else "",
        })
    for job in scraped:
        items.append({
            "type": "scraped",
            "obj": job,
            "score": job.score or 0,
            "date": job.scraped_at or job.posted_date or "",
        })

    reverse = sort.endswith("_desc")
    key = "score" if sort.startswith("score") else "date"
    items.sort(key=lambda x: x[key], reverse=reverse)

    return render_template("inbox.html", items=items, sort=sort,
                           email_count=len(emails), scraped_count=len(scraped))


@bp.route("/emails")
def emails_list():
    """All classified emails with filters."""
    repo = _repo()
    classification = request.args.get("classification")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 50
    offset = (page - 1) * per_page

    emails = repo.get_emails_classified(
        classification=classification, limit=per_page, offset=offset
    )
    for email in emails:
        email.signals = _sort_signals(repo.get_signals_for_email(email.id))

    return render_template(
        "emails.html", emails=emails, classification=classification, page=page
    )


@bp.route("/api/feedback/<email_id>", methods=["POST"])
def submit_feedback(email_id: str):
    """Record user feedback on an email classification."""
    repo = _repo()
    label = _get_param("label")
    notes = _get_param("notes")

    if label not in ("worth_checking", "skip", "not_a_job"):
        return "Invalid label", 400

    feedback = UserFeedback(id=None, email_id=email_id, label=label, notes=notes)
    repo.insert_feedback(feedback)

    # Return the next card or empty div (for htmx swap)
    return '<div class="feedback-done">Labeled!</div>'


@bp.route("/api/feedback/scraped/<int:job_id>", methods=["POST"])
def submit_scraped_feedback(job_id: int):
    """Record user feedback on a scraped job."""
    repo = _repo()
    label = _get_param("label")

    if label not in ("worth_checking", "skip", "not_a_job"):
        return "Invalid label", 400

    repo.update_scraped_job_label(job_id, label)
    return '<div class="feedback-done">Labeled!</div>'


@bp.route("/api/scraped/<int:job_id>/expired", methods=["POST"])
def toggle_expired(job_id: int):
    """Toggle expired flag on a scraped job."""
    repo = _repo()
    new_val = repo.toggle_scraped_job_expired(job_id)
    return render_template(
        "partials/expired_badge.html", job_id=job_id, expired=new_val
    )


@bp.route("/stats")
def stats():
    """Dashboard statistics with charts."""
    repo = _repo()
    data = repo.get_dashboard_stats(score_threshold=settings.score_threshold)
    data["min_training_samples"] = settings.min_training_samples
    return render_template("stats.html", data=data)


@bp.route("/settings")
def settings_page():
    """Settings page."""
    repo = _repo()
    sync_days = repo.get_setting("sync_days", "7")
    scrape_threshold = repo.get_setting(
        "scrape_confidence_threshold", str(settings.scrape_confidence_threshold)
    )
    return render_template(
        "settings.html", sync_days=sync_days, scrape_threshold=scrape_threshold
    )


@bp.route("/api/settings/sync_days", methods=["POST"])
def update_sync_days():
    """Update the sync_days setting."""
    repo = _repo()
    value = _get_param("value", "7")
    try:
        days = int(value)
        if not 1 <= days <= 90:
            return jsonify({"status": "error", "message": "Must be between 1 and 90"}), 400
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid number"}), 400

    repo.set_setting("sync_days", str(days))
    return jsonify({"status": "ok", "value": days})


@bp.route("/api/settings/scrape_confidence_threshold", methods=["POST"])
def update_scrape_threshold():
    """Update the scrape confidence threshold setting."""
    repo = _repo()
    value = _get_param("value", str(settings.scrape_confidence_threshold))
    try:
        threshold = float(value)
        if not 0.0 <= threshold <= 1.0:
            return jsonify({"status": "error", "message": "Must be between 0.0 and 1.0"}), 400
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid number"}), 400

    repo.set_setting("scrape_confidence_threshold", str(threshold))
    return jsonify({"status": "ok", "value": threshold})


@bp.route("/api/sync", methods=["POST"])
def sync_emails():
    """Fetch new emails from Gmail and run classification."""
    from datetime import datetime, timedelta

    from jobpilot.gmail.auth import GmailAuth
    from jobpilot.gmail.client import GmailClient
    from jobpilot.gmail.fetcher import fetch_new_emails
    from jobpilot.web.app import (
        _classify_unprocessed,
        _parse_existing_digests,
        _score_pending_jobs,
    )

    repo = _repo()

    try:
        auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)
        creds = auth.get_credentials()
    except Exception:
        logger.exception("Auth failed during sync")
        return jsonify({"status": "auth_required"}), 401

    try:
        sync_days = int(repo.get_setting("sync_days", "7"))
        since = datetime.now() - timedelta(days=sync_days)
        client = GmailClient(creds)
        new_emails = fetch_new_emails(client, repo, since=since)
        _classify_unprocessed(repo)
        _parse_existing_digests(repo)
        _score_pending_jobs(repo)
        _scrape_low_confidence_jobs(repo)
        return jsonify({"status": "ok", "new_emails": new_emails})
    except Exception:
        logger.exception("Sync failed")
        return jsonify({"status": "error", "message": "Sync failed, check server logs"}), 500


def _scrape_low_confidence_jobs(repo) -> None:
    """Scrape full descriptions for jobs with low scoring confidence."""
    from jobpilot.classifier.rules import RuleBasedScorer
    from jobpilot.scraper.job_page import JobPageScraper

    scrape_threshold = float(
        repo.get_setting("scrape_confidence_threshold", str(settings.scrape_confidence_threshold))
    )
    jobs = repo.get_jobs_needing_scrape(settings.score_threshold, scrape_threshold)
    if not jobs:
        return

    scraper = JobPageScraper()
    scorer = RuleBasedScorer()
    logger.info("Scraping %d low-confidence jobs", len(jobs))

    for job in jobs:
        description = scraper.scrape(job.url)
        if description:
            repo.update_scraped_job_description(job.id, description)
            text = f"{job.title} {job.company or ''} {job.location or ''} {description}"
            result = scorer.score(job.title, text)
            repo.update_scraped_job_scores(job.id, result.score, None, result.classification)
        repo.mark_scrape_attempted(job.id)
        time.sleep(2)
