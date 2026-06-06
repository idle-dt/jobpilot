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
from jobpilot.services.inbox_service import (
    DEFAULT_SORT,
    VALID_SORTS,
    InboxService,
    sort_signals,
)
from jobpilot.services.ml_export_service import VALID_MODEL_TYPES, MLExportService
from jobpilot.storage.models import UserFeedback
from jobpilot.storage.repository import Repository
from jobpilot.web.app import limiter
from jobpilot.web.request_utils import get_param as _get_param

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)

# --- Route constants ---
EMAILS_PER_PAGE = 50


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
    service = InboxService(_repo())
    sort = request.args.get("sort", DEFAULT_SORT)
    if sort not in VALID_SORTS:
        sort = DEFAULT_SORT
    items = service.build_review_queue(sort)
    review_total, worth_checking_count, skip_count = service.count_review_totals()
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
        email.signals = sort_signals(repo.get_signals_for_email(email.id))

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
    model_type = request.args.get("model_type", "scoring")
    if model_type not in VALID_MODEL_TYPES:
        return jsonify({"status": "error", "message": "Invalid model_type"}), 400

    export = MLExportService(_repo()).build_export(model_type)

    filename = f"jobpilot_ml_export_{model_type}_{datetime.now().strftime('%Y-%m-%d')}.json"
    response = current_app.response_class(
        json_module.dumps(export, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
    return response
