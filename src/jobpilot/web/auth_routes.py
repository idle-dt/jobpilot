"""OAuth2 web flow endpoints for Google/Gmail authentication."""

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from google.auth.exceptions import GoogleAuthError
from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from requests.exceptions import RequestException

from jobpilot.config import settings
from jobpilot.gmail.auth import SCOPES

logger = logging.getLogger(__name__)

bp_auth = Blueprint("auth", __name__, url_prefix="/auth")

# File to persist OAuth flow state across the Google redirect,
# since Flask session cookies may not survive the cross-site round-trip.
_OAUTH_STATE_PATH = Path.home() / ".jobpilot" / ".oauth_pending"

# Hosts for which RFC 8252 section 8.3 permits a plain-HTTP redirect URI.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# oauthlib escape hatches; both are read from the environment at exchange time.
_INSECURE_TRANSPORT_ENV = "OAUTHLIB_INSECURE_TRANSPORT"
_RELAX_TOKEN_SCOPE_ENV = "OAUTHLIB_RELAX_TOKEN_SCOPE"

# Everything the token exchange can raise: OAuth protocol errors, credential
# errors, network faults, malformed client secrets, and unreadable files.
_TOKEN_EXCHANGE_ERRORS = (
    OAuth2Error,
    GoogleAuthError,
    RequestException,
    ValueError,
    OSError,
)


def _build_redirect_uri() -> str:
    """Return the OAuth redirect URI registered with the Google client."""
    return f"http://localhost:{settings.server_port}/auth/callback"


def _allow_insecure_loopback_transport() -> None:
    """Let oauthlib accept the plain-HTTP callback when it targets loopback.

    oauthlib refuses any non-HTTPS OAuth response unless the insecure-transport
    variable is set. RFC 8252 section 8.3 permits plain HTTP on loopback for
    native apps, which is how JobPilot runs; a non-loopback redirect URI still
    requires HTTPS. Relaxing the scope check keeps Google's normalization of the
    granted scopes from aborting an otherwise successful exchange.
    """
    if urlparse(_build_redirect_uri()).hostname not in _LOOPBACK_HOSTS:
        return
    os.environ[_INSECURE_TRANSPORT_ENV] = "1"
    os.environ[_RELAX_TOKEN_SCOPE_ENV] = "1"


def _build_flow(state: str | None = None) -> Flow:
    """Construct the OAuth flow from the configured client secrets file."""
    return Flow.from_client_secrets_file(
        str(settings.gmail_credentials_path),
        scopes=SCOPES,
        state=state,
        redirect_uri=_build_redirect_uri(),
    )


def _consume_pending_state() -> dict | None:
    """Read and delete the one-time handshake file, or None if unusable."""
    if not _OAUTH_STATE_PATH.exists():
        return None
    try:
        return json.loads(_OAUTH_STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        logger.exception("Unreadable pending OAuth state")
        return None
    finally:
        _OAUTH_STATE_PATH.unlink(missing_ok=True)


@bp_auth.route("/login")
def login() -> str:
    """Render the sign-in page."""
    credentials_exist = settings.gmail_credentials_path.exists()
    return render_template("login.html", credentials_exist=credentials_exist)


@bp_auth.route("/google")
def google_auth() -> Response | str:
    """Start the handshake and send the user to Google's consent screen."""
    if not settings.gmail_credentials_path.exists():
        return render_template(
            "login.html",
            credentials_exist=False,
            error="OAuth credentials file not found. Please set up credentials.json first.",
        )

    flow = _build_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Persist state and code_verifier to disk so the callback can use them
    pending = {"state": state}
    if getattr(flow, "code_verifier", None):
        pending["code_verifier"] = flow.code_verifier
    _OAUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OAUTH_STATE_PATH.write_text(json.dumps(pending))

    return redirect(authorization_url)


@bp_auth.route("/callback")
def callback() -> Response:
    """Exchange the authorization code for credentials and store them."""
    pending = _consume_pending_state()
    if pending is None:
        flash("No pending OAuth flow. Please try again.")
        return redirect(url_for("auth.login"))

    flow = _build_flow(pending.get("state"))
    code_verifier = pending.get("code_verifier")
    if code_verifier:
        flow.code_verifier = code_verifier

    _allow_insecure_loopback_transport()
    try:
        flow.fetch_token(authorization_response=request.url)
    except _TOKEN_EXCHANGE_ERRORS:
        logger.exception("OAuth token exchange failed")
        flash("Authentication failed. Please try again.")
        return redirect(url_for("auth.login"))

    settings.gmail_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.gmail_token_path.write_text(flow.credentials.to_json())
    session["authenticated"] = True
    return redirect(url_for("main.inbox"))


@bp_auth.route("/logout")
def logout() -> Response:
    """Clear the session and return to the sign-in page."""
    session.clear()
    return redirect(url_for("auth.login"))
