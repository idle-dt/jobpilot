"""Route handlers for the web UI."""

import json as json_module
import logging
import time
from datetime import datetime

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
    valid_sorts = {"score_desc", "score_asc", "date_desc", "date_asc"}
    sort = request.args.get("sort", "score_desc")
    if sort not in valid_sorts:
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

    # Load ML predictions for displayed items
    email_ids = [item["obj"].id for item in items if item["type"] == "email"]
    job_ids = [str(item["obj"].id) for item in items if item["type"] == "scraped"]
    email_preds = repo.get_predictions_for_items("email", email_ids) if email_ids else {}
    job_preds = repo.get_predictions_for_items("scraped_job", job_ids) if job_ids else {}
    for item in items:
        if item["type"] == "email":
            item["predictions"] = email_preds.get(item["obj"].id, [])
        else:
            item["predictions"] = job_preds.get(str(item["obj"].id), [])

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

    _maybe_auto_retrain(repo)
    return '<div class="feedback-done">Labeled!</div>'


@bp.route("/api/feedback/scraped/<int:job_id>", methods=["POST"])
def submit_scraped_feedback(job_id: int):
    """Record user feedback on a scraped job."""
    repo = _repo()
    label = _get_param("label")

    if label not in ("worth_checking", "skip", "not_a_job"):
        return "Invalid label", 400

    repo.update_scraped_job_label(job_id, label)

    _maybe_auto_retrain(repo)
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


def _maybe_auto_retrain(repo) -> None:
    """Check if conditions are met for automatic retraining after feedback."""
    try:
        from jobpilot.classifier.ml_trainer import MLTrainer
        trainer = MLTrainer(repo)
        for model_type in ("noise", "scoring"):
            if trainer.should_retrain(model_type):
                logger.info("Auto-retraining %s model", model_type)
                trainer.train_all(model_type)
    except Exception:
        logger.exception("Auto-retrain check failed")


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


# --- ML API Routes ---


@bp.route("/api/ml/train", methods=["POST"])
def ml_train():
    """Train all ML algorithms for a model type."""
    from jobpilot.classifier.ml_trainer import MLTrainer

    repo = _repo()
    model_type = _get_param("model_type", "scoring")
    if model_type not in ("noise", "scoring"):
        return jsonify({"status": "error", "message": "Invalid model_type"}), 400

    trainer = MLTrainer(repo)
    model_ids = trainer.train_all(model_type)

    if not model_ids:
        return jsonify({"status": "error", "message": "Not enough training data"}), 400

    # Gather metrics for response
    results = {}
    for mid in model_ids:
        mv = repo.get_model_version(mid)
        if mv:
            results[mv.algorithm] = {
                "accuracy": mv.accuracy,
                "precision": mv.precision_score,
                "recall": mv.recall_score,
                "f1": mv.f1_score,
                "is_active": mv.is_active,
            }

    return jsonify({"status": "ok", "results": results})


@bp.route("/api/ml/activate", methods=["POST"])
def ml_activate():
    """Set active algorithm for a model type."""
    repo = _repo()
    model_type = _get_param("model_type", "")
    algorithm = _get_param("algorithm", "")

    if model_type not in ("noise", "scoring"):
        return jsonify({"status": "error", "message": "Invalid model_type"}), 400
    if algorithm not in ("LR", "RF", "GBC", "SVM"):
        return jsonify({"status": "error", "message": "Invalid algorithm"}), 400

    models = repo.get_model_versions_by_type(model_type)
    match = next((m for m in models if m.algorithm == algorithm), None)
    if not match:
        return jsonify({"status": "error", "message": "Model not found"}), 404

    repo.activate_model(model_type, algorithm)
    return jsonify({"status": "ok", "algorithm": algorithm})


@bp.route("/api/ml/export")
def ml_export():
    """Download model data as JSON."""
    from jobpilot.classifier.rules import FEATURE_NAMES, compute_features

    repo = _repo()
    model_type = request.args.get("model_type", "scoring")
    if model_type not in ("noise", "scoring"):
        return jsonify({"status": "error", "message": "Invalid model_type"}), 400

    models = repo.get_model_versions_by_type(model_type)

    # Training data
    if model_type == "noise":
        raw_data = repo.get_noise_training_data()
    else:
        raw_data = repo.get_scoring_training_data()

    samples = []
    for d in raw_data:
        subject = d.get("subject") or ""
        body = d.get("body") or d.get("body_text") or ""
        features = compute_features(subject, body)
        samples.append({
            "item_type": d.get("item_type", "email"),
            "item_id": d.get("item_id") or d.get("email_id") or "",
            "title": subject,
            "features": features,
            "user_label": d.get("label"),
        })

    # Algorithms
    algorithms = {}
    for mv in models:
        feat_data = {}
        if mv.feature_names:
            try:
                feat_data = json_module.loads(mv.feature_names)
            except (json_module.JSONDecodeError, TypeError):
                pass
        importances = feat_data.get("importances", [])
        importance_dict = {}
        if importances:
            for i, name in enumerate(FEATURE_NAMES):
                if i < len(importances):
                    importance_dict[name] = round(importances[i], 4)

        algorithms[mv.algorithm] = {
            "metrics": {
                "accuracy": mv.accuracy,
                "precision": mv.precision_score,
                "recall": mv.recall_score,
                "f1": mv.f1_score,
            },
            "feature_importances": importance_dict,
            "is_active": mv.is_active,
        }

    # Predictions for labeled items
    comparison = repo.get_recent_predictions_comparison(limit=50)
    predictions = []
    disagreements = []
    for item in comparison:
        pred_entry = {
            "item_type": item["item_type"],
            "item_id": item["item_id"],
            "title": item.get("title", ""),
            "user_label": item.get("user_label", ""),
            "rule_score": item.get("raw_score"),
            "ml_predictions": {},
        }
        disagree_algos = []
        for algo, pdata in item.get("predictions", {}).items():
            pred_entry["ml_predictions"][algo] = {
                "prediction": pdata["prediction"],
                "probability": pdata["probability"],
            }
            if pdata["prediction"] != item.get("user_label"):
                disagree_algos.append(algo)
        predictions.append(pred_entry)
        if disagree_algos:
            disagreements.append({
                "item_id": item["item_id"],
                "title": item.get("title", ""),
                "user_label": item.get("user_label", ""),
                "models_that_disagree": disagree_algos,
            })

    export = {
        "exported_at": datetime.now().isoformat(),
        "model_type": model_type,
        "training_data": {
            "feature_names": FEATURE_NAMES,
            "samples": samples,
        },
        "algorithms": algorithms,
        "predictions": predictions,
        "disagreements": disagreements,
    }

    filename = f"jobpilot_ml_export_{model_type}_{datetime.now().strftime('%Y-%m-%d')}.json"
    response = current_app.response_class(
        json_module.dumps(export, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
    return response
