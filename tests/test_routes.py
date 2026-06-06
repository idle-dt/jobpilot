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
