"""Tests for the Google OAuth web flow endpoints."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
from flask.testing import FlaskClient
from jobpilot.web import auth_routes
from oauthlib.oauth2.rfc6749.errors import InsecureTransportError
from oauthlib.oauth2.rfc6749.utils import is_secure_transport

_OAUTH_ENV_VARS = ("OAUTHLIB_INSECURE_TRANSPORT", "OAUTHLIB_RELAX_TOKEN_SCOPE")


@pytest.fixture(autouse=True)
def clean_oauth_env(monkeypatch) -> Iterator[None]:
    """Unset the oauthlib escape hatches around every test.

    The code under test writes os.environ directly, so monkeypatch has no record
    of those writes to roll back; clearing on the way out keeps the flags from
    leaking into the rest of the pytest session.
    """
    for name in _OAUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
    # Not monkeypatch.delenv: that would record "1" and restore it on teardown.
    for name in _OAUTH_ENV_VARS:
        os.environ.pop(name, None)


@pytest.fixture
def pending_state(monkeypatch, tmp_path: Path) -> Path:
    """Point the OAuth handshake at a temp file holding a pending state."""
    state_path = tmp_path / ".oauth_pending"
    state_path.write_text(json.dumps({"state": "test-state"}))
    monkeypatch.setattr(auth_routes, "_OAUTH_STATE_PATH", state_path)
    return state_path


def _stub_flow(fetch_token_side_effect=None, token_json: str = "{}") -> object:
    """Build a stand-in for google_auth_oauthlib's Flow."""

    def fetch_token(**_kwargs) -> None:
        if fetch_token_side_effect is not None:
            raise fetch_token_side_effect

    return SimpleNamespace(
        fetch_token=fetch_token,
        credentials=SimpleNamespace(to_json=lambda: token_json),
    )


def test_loopback_transport_is_permitted(monkeypatch) -> None:
    """A loopback callback URL becomes acceptable to oauthlib."""
    callback_url = "http://localhost:5050/auth/callback"
    assert not is_secure_transport(callback_url)

    auth_routes._allow_insecure_loopback_transport()

    assert is_secure_transport(callback_url)


def test_loopback_transport_relaxes_scope_check() -> None:
    """Scope normalization by Google must not abort the token exchange."""
    auth_routes._allow_insecure_loopback_transport()

    assert os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] == "1"


def test_non_loopback_redirect_still_requires_https(monkeypatch) -> None:
    """A public redirect URI does not get the insecure-transport exemption."""
    monkeypatch.setattr(
        auth_routes, "_build_redirect_uri", lambda: "http://example.com/auth/callback"
    )

    auth_routes._allow_insecure_loopback_transport()

    assert not is_secure_transport("http://example.com/auth/callback")


def test_callback_without_pending_state_redirects(
    client: FlaskClient, monkeypatch, tmp_path: Path
) -> None:
    """A callback with no stored handshake sends the user back to login."""
    monkeypatch.setattr(
        auth_routes, "_OAUTH_STATE_PATH", tmp_path / "missing" / ".oauth_pending"
    )

    resp = client.get("/auth/callback?code=abc&state=test-state")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/auth/login"


def test_callback_flashes_on_oauth_error(
    client: FlaskClient, monkeypatch, pending_state: Path
) -> None:
    """An oauthlib failure redirects to login instead of raising a 500."""
    monkeypatch.setattr(
        auth_routes, "_build_flow", lambda state=None: _stub_flow(InsecureTransportError())
    )

    resp = client.get("/auth/callback?code=abc&state=test-state")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/auth/login"


def test_callback_error_details_not_leaked(
    client: FlaskClient, monkeypatch, pending_state: Path
) -> None:
    """The flashed message is generic, with no exception internals."""
    monkeypatch.setattr(
        auth_routes, "_build_flow", lambda state=None: _stub_flow(InsecureTransportError())
    )

    body = client.get(
        "/auth/callback?code=abc&state=test-state", follow_redirects=True
    ).get_data(as_text=True)

    assert "Authentication failed" in body
    assert "InsecureTransportError" not in body
    assert "insecure_transport" not in body


def test_callback_success_writes_token(
    app: Flask, client: FlaskClient, monkeypatch, pending_state: Path, tmp_path: Path
) -> None:
    """A successful exchange persists the credentials and lands on the inbox."""
    token_path = tmp_path / "token.json"
    monkeypatch.setattr(auth_routes.settings, "gmail_token_path", token_path)
    monkeypatch.setattr(
        auth_routes, "_build_flow", lambda state=None: _stub_flow(token_json='{"token": "t"}')
    )

    resp = client.get("/auth/callback?code=abc&state=test-state")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    assert json.loads(token_path.read_text()) == {"token": "t"}


def test_callback_with_corrupt_state_redirects(
    client: FlaskClient, monkeypatch, tmp_path: Path
) -> None:
    """A truncated handshake file is treated as no pending flow, not a 500."""
    state_path = tmp_path / ".oauth_pending"
    state_path.write_text('{"state": "trunca')
    monkeypatch.setattr(auth_routes, "_OAUTH_STATE_PATH", state_path)

    resp = client.get("/auth/callback?code=abc&state=test-state")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/auth/login"
    assert not state_path.exists()
