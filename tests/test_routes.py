"""Smoke tests for route handlers, including the extracted settings blueprint."""

import json

import pytest
from flask.testing import FlaskClient


@pytest.fixture
def authed_client(client: FlaskClient, monkeypatch) -> FlaskClient:
    """A test client that passes the Gmail auth gate."""
    monkeypatch.setattr(
        "jobpilot.gmail.auth.GmailAuth.is_authenticated", lambda self: True
    )
    return client


def test_inbox_renders(authed_client: FlaskClient) -> None:
    """The inbox review queue renders on an empty database."""
    assert authed_client.get("/").status_code == 200


def test_inbox_invalid_sort_falls_back(authed_client: FlaskClient) -> None:
    """An invalid sort query parameter does not error the page."""
    assert authed_client.get("/?sort=bogus").status_code == 200


def test_emails_page_renders(authed_client: FlaskClient) -> None:
    """The classified-emails list renders on an empty database."""
    assert authed_client.get("/emails").status_code == 200


def test_emails_not_job_related_view_renders(authed_client: FlaskClient) -> None:
    """Rejected mail is reachable under its own filter, labelled as such."""
    resp = authed_client.get("/emails?view=not_job_related")
    assert resp.status_code == 200
    assert b"Not Job Related" in resp.data


def test_emails_invalid_view_falls_back(authed_client: FlaskClient) -> None:
    """A view outside the allowlist renders the default list, not an error."""
    resp = authed_client.get("/emails?view=bogus")
    assert resp.status_code == 200
    assert b"Classified Emails" in resp.data


def test_settings_page_renders(authed_client: FlaskClient) -> None:
    """The settings page renders via SettingsService."""
    assert authed_client.get("/settings").status_code == 200


def test_ml_export_rejects_invalid_model_type(authed_client: FlaskClient) -> None:
    """An unknown model_type returns 400 rather than building an export."""
    resp = authed_client.get("/api/ml/export?model_type=bogus")
    assert resp.status_code == 400


def test_ml_export_returns_json_attachment(authed_client: FlaskClient) -> None:
    """A valid export is JSON delivered as a download with the expected shape."""
    resp = authed_client.get("/api/ml/export?model_type=scoring")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert "attachment" in resp.headers["Content-Disposition"]
    payload = json.loads(resp.data)
    assert payload["model_type"] == "scoring"


def test_settings_sync_days_accepts_valid_value(authed_client: FlaskClient) -> None:
    """The relocated settings blueprint accepts an in-range sync_days value."""
    resp = authed_client.post("/api/settings/sync_days", data={"value": "14"})
    assert resp.status_code == 200
    assert resp.get_json()["value"] == 14


def test_settings_sync_days_rejects_out_of_range(authed_client: FlaskClient) -> None:
    """An out-of-range sync_days value is rejected with 400."""
    resp = authed_client.post("/api/settings/sync_days", data={"value": "999"})
    assert resp.status_code == 400


def _insert_active_model(repo, model_type: str) -> int:
    """Insert an active model version of the given type and return its id."""
    from jobpilot.storage.models import ModelVersion

    return repo.insert_model_version(ModelVersion(
        id=None, version=repo.get_next_version(model_type), training_samples=30,
        model_blob=b"blob", model_type=model_type, algorithm="LR", is_active=True,
    ))


def test_reset_scoring_criteria_returns_counts(authed_client: FlaskClient) -> None:
    """The reset endpoint reports how many labels and models it retired."""
    repo = authed_client.application.config["repo"]
    _insert_active_model(repo, "scoring")

    resp = authed_client.post("/api/settings/reset-scoring-criteria")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "ok"
    assert payload["excluded_labels"] == 0
    assert payload["deactivated_models"] == 1


def test_preference_change_spares_the_noise_model(authed_client: FlaskClient) -> None:
    """Editing a scoring preference retires the scoring model only."""
    repo = authed_client.application.config["repo"]
    _insert_active_model(repo, "scoring")
    noise_id = _insert_active_model(repo, "noise")

    resp = authed_client.post(
        "/api/preferences", data={"category": "location_primary", "value": "reykjavik"}
    )

    assert resp.status_code == 200
    assert repo.get_active_model("scoring") is None
    assert repo.get_active_model("noise").id == noise_id


def test_settings_page_shows_dormancy_progress(authed_client: FlaskClient) -> None:
    """A dormant scoring model is reported with its progress under current criteria."""
    resp = authed_client.get("/settings")

    assert resp.status_code == 200
    assert (
        "Scoring model dormant — 0 of 30 labels under current criteria."
        in resp.data.decode()
    )


def test_stats_page_marks_retired_criteria_models(authed_client: FlaskClient) -> None:
    """A scoring model trained before the cutoff is chipped as retired in the lab."""
    repo = authed_client.application.config["repo"]
    model_id = _insert_active_model(repo, "scoring")
    repo.conn.execute(
        "UPDATE model_versions SET trained_at = ? WHERE id = ?",
        ("2026-01-01 00:00:00", model_id),
    )
    repo.commit()
    authed_client.post("/api/settings/reset-scoring-criteria")

    resp = authed_client.get("/stats")

    assert resp.status_code == 200
    assert "Retired criteria" in resp.data.decode()
