"""Route handlers for the application tracker."""

import logging

from flask import Blueprint, current_app, jsonify, render_template, request

from jobpilot.services.tracker_service import (
    APPLICATION_STATUSES,
    DEFAULT_TRACKER_SORT,
    PATCH_BLOCKED_FIELDS,
    STATUS_LABELS,
    TrackerService,
    canonical_tracker_sort,
)
from jobpilot.storage.repository import Repository
from jobpilot.web.request_utils import get_param

logger = logging.getLogger(__name__)

bp_tracker = Blueprint("tracker", __name__)


def _service() -> TrackerService:
    """Get a TrackerService from the current Flask app config."""
    repo: Repository = current_app.config["repo"]
    return TrackerService(repo)


@bp_tracker.route("/tracker")
def tracker_page() -> str:
    """Main tracker page with status filter pills and table."""
    status_filter = request.args.get("status", "")
    sort = canonical_tracker_sort(request.args.get("sort", DEFAULT_TRACKER_SORT))
    apps, counts, total = _service().list_applications(status_filter, sort)

    return render_template(
        "tracker.html",
        apps=apps,
        counts=counts,
        total=total,
        status_filter=status_filter,
        sort=sort,
        statuses=APPLICATION_STATUSES,
        status_labels=STATUS_LABELS,
    )


@bp_tracker.route("/api/tracker/<int:app_id>")
def tracker_modal(app_id: int) -> tuple[str, int]:
    """Return modal HTML partial for an application."""
    svc = _service()
    app = svc.get_application(app_id)
    if not app:
        return "", 404
    history = svc.get_history(app_id)
    return render_template(
        "partials/tracker_modal.html",
        app=app,
        history=history,
        statuses=APPLICATION_STATUSES,
        status_labels=STATUS_LABELS,
        create_mode=False,
    ), 200


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
    company = get_param("company").strip()
    role_title = get_param("role_title").strip()
    if not company or not role_title:
        return jsonify({"status": "error", "message": "Company and role are required"}), 400

    new_id = _service().create_application(
        company=company,
        role_title=role_title,
        status=get_param("status", "applied"),
        location=get_param("location").strip() or None,
        salary_range=get_param("salary_range").strip() or None,
        job_url=get_param("job_url").strip() or None,
        platform=get_param("platform").strip() or None,
        contact_name=get_param("contact_name").strip() or None,
        contact_email=get_param("contact_email").strip() or None,
        notes=get_param("notes").strip() or None,
    )
    logger.info("Created application %d: %s at %s", new_id, role_title, company)
    return "", 204, {"HX-Redirect": "/tracker"}


@bp_tracker.route("/api/tracker/<int:app_id>/status", methods=["POST"])
def tracker_update_status(app_id: int) -> tuple[str, int]:
    """Inline status update — returns updated badge partial."""
    svc = _service()
    app = svc.get_application(app_id)
    if not app:
        return "", 404

    new_status = get_param("status")
    ok = svc.update_status(app_id, new_status)
    if not ok:
        return jsonify({"status": "error", "message": "Invalid status"}), 400

    app.status = new_status
    return render_template(
        "partials/tracker_status_badge.html",
        app=app,
        statuses=APPLICATION_STATUSES,
        status_labels=STATUS_LABELS,
    ), 200


@bp_tracker.route("/api/tracker/<int:app_id>", methods=["PATCH"])
def tracker_update(app_id: int) -> tuple:
    """Partial field update for an application."""
    svc = _service()
    app = svc.get_application(app_id)
    if not app:
        return "", 404

    data = request.get_json(silent=True) or {}
    blocked = set(data.keys()) & PATCH_BLOCKED_FIELDS
    if blocked:
        return jsonify({
            "status": "error",
            "message": f"Cannot update: {', '.join(sorted(blocked))}",
        }), 400

    fields: dict[str, str | None] = {}
    for key, val in data.items():
        cleaned = str(val).strip() if val else None
        fields[key] = cleaned or None

    if not fields:
        return jsonify({"status": "ok"}), 200

    updated = svc.update_fields(app_id, fields)
    if not updated:
        return jsonify({"status": "error", "message": "No valid fields to update"}), 400
    return jsonify({"status": "ok"}), 200


@bp_tracker.route("/api/tracker/<int:app_id>", methods=["DELETE"])
def tracker_delete(app_id: int) -> tuple:
    """Delete an application."""
    svc = _service()
    app = svc.get_application(app_id)
    if not app:
        return "", 404

    svc.delete_application(app_id)
    logger.info("Deleted application %d", app_id)
    return "", 200, {"HX-Trigger": "applicationDeleted"}
