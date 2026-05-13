"""Route handlers for the application tracker."""

import logging
import re

from flask import Blueprint, current_app, jsonify, render_template, request

from jobpilot.storage.models import Application
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

bp_tracker = Blueprint("tracker", __name__)

APPLICATION_STATUSES = [
    "saved", "applied", "screening", "technical",
    "onsite", "offer", "accepted", "rejected",
    "withdrawn", "no_response",
]

STATUS_LABELS = {
    "saved": "Saved",
    "applied": "Applied",
    "screening": "Screening",
    "technical": "Technical",
    "onsite": "Onsite",
    "offer": "Offer",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
    "no_response": "No Response",
}

_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


def _repo() -> Repository:
    """Get the repository from the current Flask app config."""
    return current_app.config["repo"]


def _get_param(name: str, default: str = "") -> str:
    """Get a parameter from form, query string, or JSON body."""
    val = request.values.get(name)
    if val:
        return val
    json_body = request.get_json(silent=True)
    if json_body:
        return json_body.get(name, default)
    return default


def _validate_url(url: str) -> str | None:
    """Return the URL if it has a safe scheme, else None."""
    if not url:
        return None
    return url if _URL_SCHEME_RE.match(url) else None


@bp_tracker.route("/tracker")
def tracker_page() -> str:
    """Main tracker page with status filter pills and table."""
    repo = _repo()
    status_filter = request.args.get("status", "")
    if status_filter and status_filter not in APPLICATION_STATUSES:
        status_filter = ""

    apps = repo.get_applications_by_status(
        status=status_filter or None,
    )
    counts = repo.count_applications_by_status()
    total = sum(counts.values())

    return render_template(
        "tracker.html",
        apps=apps,
        counts=counts,
        total=total,
        status_filter=status_filter,
        statuses=APPLICATION_STATUSES,
        status_labels=STATUS_LABELS,
    )


@bp_tracker.route("/api/tracker/<int:app_id>")
def tracker_modal(app_id: int) -> tuple[str, int]:
    """Return modal HTML partial for an application."""
    repo = _repo()
    app = repo.get_application(app_id)
    if not app:
        return "", 404
    history = repo.get_application_history(app_id)
    return render_template(
        "partials/tracker_modal.html",
        app=app,
        history=history,
        statuses=APPLICATION_STATUSES,
        status_labels=STATUS_LABELS,
        create_mode=False,
    )


@bp_tracker.route("/api/tracker/new")
def tracker_modal_new() -> str:
    """Return empty modal in create mode."""
    return render_template(
        "partials/tracker_modal.html",
        app=None,
        history=[],
        statuses=APPLICATION_STATUSES,
        status_labels=STATUS_LABELS,
        create_mode=True,
    )


@bp_tracker.route("/api/tracker", methods=["POST"])
def tracker_create() -> tuple:
    """Create a new application."""
    repo = _repo()
    company = _get_param("company").strip()
    role_title = _get_param("role_title").strip()
    if not company or not role_title:
        return jsonify({"status": "error", "message": "Company and role are required"}), 400

    status = _get_param("status", "applied")
    if status not in APPLICATION_STATUSES:
        status = "applied"

    job_url = _validate_url(_get_param("job_url").strip())

    app = Application(
        id=None,
        company=company,
        role_title=role_title,
        status=status,
        location=_get_param("location").strip() or None,
        salary_range=_get_param("salary_range").strip() or None,
        job_url=job_url,
        platform=_get_param("platform").strip() or None,
        contact_name=_get_param("contact_name").strip() or None,
        contact_email=_get_param("contact_email").strip() or None,
        notes=_get_param("notes").strip() or None,
    )
    new_id = repo.insert_application(app)
    logger.info("Created application %d: %s at %s", new_id, role_title, company)

    return "", 204, {"HX-Redirect": "/tracker"}


@bp_tracker.route("/api/tracker/<int:app_id>/status", methods=["POST"])
def tracker_update_status(app_id: int) -> tuple[str, int]:
    """Inline status update — returns updated badge partial."""
    repo = _repo()
    app = repo.get_application(app_id)
    if not app:
        return "", 404

    new_status = _get_param("status")
    if new_status not in APPLICATION_STATUSES:
        return jsonify({"status": "error", "message": "Invalid status"}), 400

    repo.update_application_status(app_id, new_status)
    app.status = new_status
    return render_template(
        "partials/tracker_status_badge.html",
        app=app,
        statuses=APPLICATION_STATUSES,
        status_labels=STATUS_LABELS,
    )


@bp_tracker.route("/api/tracker/<int:app_id>", methods=["PATCH"])
def tracker_update(app_id: int) -> tuple:
    """Partial field update for an application."""
    repo = _repo()
    app = repo.get_application(app_id)
    if not app:
        return "", 404

    data = request.get_json(silent=True) or {}
    fields: dict[str, str | None] = {}
    for key, val in data.items():
        if key == "job_url":
            fields[key] = _validate_url(str(val).strip())
        else:
            cleaned = str(val).strip() if val else None
            fields[key] = cleaned or None

    if not fields:
        return jsonify({"status": "ok"})

    repo.update_application(app_id, **fields)
    return jsonify({"status": "ok"})


@bp_tracker.route("/api/tracker/<int:app_id>", methods=["DELETE"])
def tracker_delete(app_id: int) -> tuple:
    """Delete an application."""
    repo = _repo()
    app = repo.get_application(app_id)
    if not app:
        return "", 404

    repo.delete_application(app_id)
    logger.info("Deleted application %d", app_id)
    return "", 200, {"HX-Trigger": "applicationDeleted"}
