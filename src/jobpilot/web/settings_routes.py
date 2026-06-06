"""Route handlers for settings and user preferences."""

import logging

from flask import Blueprint, current_app, jsonify, render_template

from jobpilot.services.settings_service import SettingsService
from jobpilot.storage.repository import Repository
from jobpilot.web.request_utils import get_param as _get_param

logger = logging.getLogger(__name__)

bp_settings = Blueprint("settings", __name__)

# Bounds for settings inputs.
MAX_SYNC_DAYS = 90
MAX_PREFERENCE_LENGTH = 100


def _repo() -> Repository:
    """Get the repository from the current Flask app config."""
    return current_app.config["repo"]


@bp_settings.route("/settings")
def settings_page():
    """Settings page."""
    context = SettingsService(_repo()).build_context()
    return render_template("settings.html", **context)


@bp_settings.route("/api/settings/sync_days", methods=["POST"])
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


@bp_settings.route("/api/preferences", methods=["POST"])
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


@bp_settings.route("/api/preferences", methods=["DELETE"])
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


@bp_settings.route("/api/preferences/domain/toggle", methods=["POST"])
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


@bp_settings.route("/api/settings/score_threshold", methods=["POST"])
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


@bp_settings.route("/api/settings/drop-scores", methods=["POST"])
def drop_scores():
    """Reset all scores so jobs are re-classified on next sync."""
    repo = _repo()
    count = repo.jobs.drop_all_scores()
    repo.invalidate_active_models()
    return jsonify({"status": "ok", "count": count})


@bp_settings.route("/api/settings/salary", methods=["POST"])
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


@bp_settings.route("/api/settings/arbeitnow", methods=["POST"])
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
