"""Route handlers for the web UI."""

import json as json_module
import logging
import re
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
)

from jobpilot.config import settings
from jobpilot.scraper.browser import ALLOWED_SITES
from jobpilot.storage.models import ExtractedSignal, UserFeedback
from jobpilot.storage.repository import Repository
from jobpilot.web.app import limiter
from jobpilot.web.request_utils import get_param as _get_param

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)

# --- Route constants ---
INBOX_REVIEW_LIMIT = 50
EMAILS_PER_PAGE = 50
NOISE_CONFIDENCE_THRESHOLD = 0.3
MAX_SYNC_DAYS = 90
MAX_PREFERENCE_LENGTH = 100
EXPORT_PREDICTIONS_LIMIT = 50

SIGNAL_PRIORITY = {
    "tech_stack": 0,
    "location": 1,
    "salary": 2,
    "job_title": 3,
    "seniority": 4,
    "negative": 5,
    "platform": 6,
}


def _sort_signals(signals: list[ExtractedSignal]) -> list[ExtractedSignal]:
    """Sort signals by priority (tech_stack first, platform last)."""
    return sorted(signals, key=lambda s: SIGNAL_PRIORITY.get(s.signal_type, 99))


def _repo() -> Repository:
    """Get the repository from the current Flask app config."""
    return current_app.config["repo"]


EMAIL_ID_PATTERN = re.compile(r"^[a-f0-9]{10,20}$")


def _validate_email_id(email_id: str) -> bool:
    """Validate that email_id matches Gmail message ID format."""
    return bool(EMAIL_ID_PATTERN.match(email_id))


@bp.route("/")
def inbox():
    """Review queue — emails needing user feedback."""
    repo = _repo()
    valid_sorts = {"score_desc", "score_asc", "date_desc", "date_asc"}
    sort = request.args.get("sort", "score_desc")
    if sort not in valid_sorts:
        sort = "score_desc"
    emails = repo.get_emails_for_review(limit=INBOX_REVIEW_LIMIT)

    # Also get scraped jobs for review
    scraped = repo.get_scraped_jobs_for_review(limit=INBOX_REVIEW_LIMIT)

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
    desc_map = repo.get_descriptions_for_emails(email_ids) if email_ids else {}
    for item in items:
        if item["type"] == "email":
            desc_data = desc_map.get(item["obj"].id)
            item["description"] = desc_data[0] if desc_data else None
            item["matched_signals"] = desc_data[1] if desc_data else None
            item["predictions"] = email_preds.get(item["obj"].id, [])
        else:
            item["predictions"] = job_preds.get(str(item["obj"].id), [])
        # Flag items the active noise model confidently marks as not-a-job
        item["noise_flag"] = any(
            p.get("model_type") == "noise"
            and p.get("is_active")
            and p.get("prediction") == "not_a_job"
            and (p.get("probability") or 1) < NOISE_CONFIDENCE_THRESHOLD
            for p in item["predictions"]
        )

    review_total = (
        repo.count_emails_for_review()
        + repo.count_scraped_jobs_for_review()
    )
    worth_checking_count = (
        repo.count_emails_for_review("worth_checking")
        + repo.count_scraped_jobs_for_review("worth_checking")
    )
    skip_count = review_total - worth_checking_count

    return render_template(
        "inbox.html", items=items, sort=sort,
        review_total=review_total,
        worth_checking_count=worth_checking_count,
        skip_count=skip_count,
    )


@bp.route("/emails")
def emails_list():
    """All classified emails with filters."""
    repo = _repo()
    classification = request.args.get("classification")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = EMAILS_PER_PAGE
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
    if not _validate_email_id(email_id):
        return "Invalid email ID", 400
    repo = _repo()
    label = _get_param("label")
    notes = _get_param("notes")

    if label not in ("worth_checking", "skip", "not_a_job"):
        return "Invalid label", 400

    feedback = UserFeedback(id=None, email_id=email_id, label=label, notes=notes)
    repo.insert_feedback(feedback)

    _maybe_auto_retrain(repo)
    response = make_response(render_template(
        "partials/feedback_done.html",
        undo_url=f"/api/feedback/{email_id}/undo",
    ))
    response.headers["HX-Trigger"] = "reviewCountChanged"
    return response


@bp.route("/api/feedback/<email_id>/undo", methods=["POST"])
def undo_feedback(email_id: str):
    """Revert user feedback on an email."""
    if not _validate_email_id(email_id):
        return "Invalid email ID", 400
    repo = _repo()
    repo.delete_feedback(email_id)
    response = make_response(render_template("partials/feedback_undone.html"))
    response.headers["HX-Trigger"] = "reviewCountChanged"
    return response


@bp.route("/api/feedback/scraped/<int:job_id>", methods=["POST"])
def submit_scraped_feedback(job_id: int):
    """Record user feedback on a scraped job."""
    repo = _repo()
    label = _get_param("label")

    if label not in ("worth_checking", "skip", "not_a_job"):
        return "Invalid label", 400

    repo.update_scraped_job_label(job_id, label)

    if label == "worth_checking":
        from jobpilot.services.tracker_service import TrackerService
        TrackerService(repo).auto_track_scraped_job(job_id)

    _maybe_auto_retrain(repo)
    response = make_response(render_template(
        "partials/feedback_done.html",
        undo_url=f"/api/feedback/scraped/{job_id}/undo",
    ))
    response.headers["HX-Trigger"] = "reviewCountChanged"
    return response


@bp.route("/api/feedback/scraped/<int:job_id>/undo", methods=["POST"])
def undo_scraped_feedback(job_id: int):
    """Revert user feedback on a scraped job."""
    repo = _repo()
    repo.update_scraped_job_label(job_id, None)
    response = make_response(render_template("partials/feedback_undone.html"))
    response.headers["HX-Trigger"] = "reviewCountChanged"
    return response


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
    score_threshold = float(
        repo.get_setting("score_threshold", str(settings.score_threshold))
    )
    data = repo.get_dashboard_stats(score_threshold=score_threshold)
    data["min_training_samples"] = settings.min_training_samples
    return render_template("stats.html", data=data)


@bp.route("/settings")
def settings_page():
    """Settings page."""
    from jobpilot.gmail.fetcher import MONITORED_DOMAINS

    repo = _repo()
    sync_days = repo.get_setting("sync_days", "7")
    score_threshold = repo.get_setting("score_threshold", str(settings.score_threshold))
    prefs = repo.get_all_preferences()

    salary_currency = repo.get_setting("salary_currency", "EUR")
    salary_min = repo.get_setting("salary_min", "")
    salary_max = repo.get_setting("salary_max", "")

    arbeitnow_enabled = repo.get_setting("arbeitnow_enabled", "false") == "true"
    arbeitnow_visa_only = repo.get_setting("arbeitnow_visa_only", "false") == "true"

    # Build domain checklist — merge known domains with DB preferences
    active_domains = {p.value for p in prefs.get("monitored_domain", [])}
    all_domains = list(dict.fromkeys(list(MONITORED_DOMAINS) + sorted(active_domains)))
    domain_list = [{"domain": d, "active": d in active_domains} for d in all_domains]

    browser_sessions = {
        site: repo.get_setting(f"browser_session_{site}", "") == "1"
        for site in ALLOWED_SITES
    }

    return render_template(
        "settings.html",
        sync_days=sync_days,
        score_threshold=score_threshold,
        prefs=prefs,
        salary_currency=salary_currency,
        salary_min=salary_min,
        salary_max=salary_max,
        arbeitnow_enabled=arbeitnow_enabled,
        arbeitnow_visa_only=arbeitnow_visa_only,
        domain_list=domain_list,
        browser_sessions=browser_sessions,
    )


@bp.route("/api/settings/sync_days", methods=["POST"])
def update_sync_days():
    """Update the sync_days setting."""
    repo = _repo()
    value = _get_param("value", "7")
    try:
        days = int(value)
        if not 1 <= days <= MAX_SYNC_DAYS:
            return jsonify(
                {"status": "error", "message": f"Must be between 1 and {MAX_SYNC_DAYS}"},
            ), 400
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid number"}), 400

    repo.set_setting("sync_days", str(days))
    return jsonify({"status": "ok", "value": days})


ALLOWED_CATEGORIES = {
    "tech_keyword_primary", "tech_keyword_secondary",
    "job_title_primary", "job_title_secondary",
    "seniority_wanted", "seniority_unwanted",
    "location_primary", "location_secondary", "location_negative",
    "negative_signal", "negation_phrase", "monitored_domain",
}
SCORING_CATEGORIES = ALLOWED_CATEGORIES - {"monitored_domain"}
ALLOWED_CURRENCIES = {"EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK"}


def _invalidate_if_scoring(repo, category: str) -> None:
    """Invalidate ML models if the preference category affects scoring."""
    if category in SCORING_CATEGORIES:
        repo.invalidate_active_models()


@bp.route("/api/preferences", methods=["POST"])
def add_preference():
    """Add a user preference tag."""
    repo = _repo()
    category = _get_param("category")
    value = _get_param("value", "").strip().lower()
    if not category or not value:
        return jsonify({"status": "error", "message": "Missing category or value"}), 400
    if category not in ALLOWED_CATEGORIES:
        return jsonify({"status": "error", "message": "Invalid category"}), 400
    if len(value) > MAX_PREFERENCE_LENGTH:
        return jsonify(
            {"status": "error", "message": f"Value too long (max {MAX_PREFERENCE_LENGTH})"},
        ), 400
    if category == "monitored_domain" and ("." not in value or " " in value):
        return jsonify({"status": "error", "message": "Invalid domain format"}), 400

    pref_id = repo.insert_preference(category, value)
    if pref_id is None:
        return jsonify({"status": "error", "message": "Already exists"}), 409

    _invalidate_if_scoring(repo, category)
    return jsonify({"status": "ok", "id": pref_id})


@bp.route("/api/preferences", methods=["DELETE"])
def remove_preference():
    """Remove a user preference tag."""
    repo = _repo()
    category = _get_param("category")
    value = _get_param("value", "").strip().lower()
    if not category or not value:
        return jsonify({"status": "error", "message": "Missing category or value"}), 400

    repo.delete_preference(category, value)
    _invalidate_if_scoring(repo, category)
    return "", 200


@bp.route("/api/preferences/domain/toggle", methods=["POST"])
def toggle_domain():
    """Add or remove a monitored domain."""
    repo = _repo()
    domain = _get_param("domain", "").strip().lower()
    active = _get_param("active", "true")
    if not domain:
        return jsonify({"status": "error", "message": "Missing domain"}), 400

    if active == "true":
        repo.insert_preference("monitored_domain", domain)
    else:
        repo.delete_preference("monitored_domain", domain)
    return jsonify({"status": "ok"})


@bp.route("/api/settings/score_threshold", methods=["POST"])
def update_score_threshold():
    """Update the score classification threshold."""
    repo = _repo()
    value = _get_param("value", "0.6")
    try:
        threshold = float(value)
        if not 0.0 <= threshold <= 1.0:
            return jsonify({"status": "error", "message": "Must be between 0.0 and 1.0"}), 400
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid number"}), 400

    repo.set_setting("score_threshold", str(threshold))
    return jsonify({"status": "ok", "value": threshold})


@bp.route("/api/settings/drop-scores", methods=["POST"])
def drop_scores():
    """Reset all scores so jobs are re-classified on next sync."""
    repo = _repo()
    count = repo.jobs.drop_all_scores()
    repo.invalidate_active_models()
    return jsonify({"status": "ok", "count": count})


@bp.route("/api/settings/salary", methods=["POST"])
def update_salary():
    """Update salary preferences."""
    repo = _repo()
    currency = _get_param("currency", "EUR").upper()
    if currency not in ALLOWED_CURRENCIES:
        return jsonify({"status": "error", "message": "Invalid currency"}), 400
    min_val = _get_param("min", "").strip()
    max_val = _get_param("max", "").strip()

    if min_val:
        try:
            min_int = int(min_val)
            if min_int < 0:
                return jsonify({"status": "error", "message": "Min must be positive"}), 400
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid min salary"}), 400
    if max_val and min_val:
        try:
            if int(max_val) < int(min_val):
                return jsonify({"status": "error", "message": "Max must be >= min"}), 400
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid max salary"}), 400

    repo.set_setting("salary_currency", currency)
    repo.set_setting("salary_min", min_val)
    repo.set_setting("salary_max", max_val)
    return jsonify({"status": "ok"})


@bp.route("/api/settings/arbeitnow", methods=["POST"])
def update_arbeitnow():
    """Update ArbeitNow API settings."""
    repo = _repo()
    enabled = _get_param("enabled", "false")
    visa_only = _get_param("visa_only", "false")
    if enabled not in ("true", "false") or visa_only not in ("true", "false"):
        return jsonify({"status": "error", "message": "Invalid boolean value"}), 400
    repo.set_setting("arbeitnow_enabled", enabled)
    repo.set_setting("arbeitnow_visa_only", visa_only)
    return jsonify({"status": "ok"})



def _maybe_auto_retrain(repo) -> None:
    """Check if conditions are met for automatic retraining after feedback."""
    from jobpilot.services.ml_service import MLService
    MLService(repo).maybe_auto_retrain()


# --- ML API Routes ---


@bp.route("/api/ml/train", methods=["POST"])
@limiter.limit("2 per minute")
def ml_train():
    """Train all ML algorithms for a model type in a subprocess."""
    from jobpilot.services.ml_service import MLService

    repo = _repo()
    model_type = _get_param("model_type", "scoring")
    if model_type not in ("noise", "scoring"):
        return jsonify({"status": "error", "message": "Invalid model_type"}), 400

    service = MLService(repo)
    success, message = service.run_manual_retrain(model_type)

    if not success:
        status_code = 504 if message == "Training timed out" else 500
        return jsonify({"status": "error", "message": message}), status_code

    # Gather metrics from DB after subprocess completed
    results = {}
    for mv in repo.get_model_versions_by_type(model_type):
        results[mv.algorithm] = {
            "accuracy": mv.accuracy,
            "precision": mv.precision_score,
            "recall": mv.recall_score,
            "f1": mv.f1_score,
            "is_active": mv.is_active,
        }

    if not results:
        return jsonify({"status": "error", "message": "Not enough training data"}), 400

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
    comparison = repo.get_recent_predictions_comparison(limit=EXPORT_PREDICTIONS_LIMIT)
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
