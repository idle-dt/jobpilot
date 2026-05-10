"""OAuth2 web flow endpoints for Google/Gmail authentication."""

import json
import logging
import os
from pathlib import Path

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from google_auth_oauthlib.flow import Flow

from jobpilot.config import settings
from jobpilot.gmail.auth import SCOPES

# Allow OAuth over HTTP only in debug mode (local development)
if settings.debug:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

logger = logging.getLogger(__name__)

bp_auth = Blueprint("auth", __name__, url_prefix="/auth")

# File to persist OAuth flow state across the Google redirect,
# since Flask session cookies may not survive the cross-site round-trip.
_OAUTH_STATE_PATH = Path.home() / ".jobpilot" / ".oauth_pending"


def _build_redirect_uri() -> str:
    return f"http://localhost:{settings.server_port}/auth/callback"


@bp_auth.route("/login")
def login() -> str:
    credentials_exist = settings.gmail_credentials_path.exists()
    return render_template("login.html", credentials_exist=credentials_exist)


@bp_auth.route("/google")
def google_auth():
    if not settings.gmail_credentials_path.exists():
        return render_template(
            "login.html",
            credentials_exist=False,
            error="OAuth credentials file not found. Please set up credentials.json first.",
        )

    flow = Flow.from_client_secrets_file(
        str(settings.gmail_credentials_path),
        scopes=SCOPES,
        redirect_uri=_build_redirect_uri(),
    )
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Persist state and code_verifier to disk so the callback can use them
    pending = {"state": state}
    if hasattr(flow, "code_verifier") and flow.code_verifier:
        pending["code_verifier"] = flow.code_verifier
    _OAUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OAUTH_STATE_PATH.write_text(json.dumps(pending))

    return redirect(authorization_url)


@bp_auth.route("/callback")
def callback():
    if not _OAUTH_STATE_PATH.exists():
        flash("No pending OAuth flow. Please try again.")
        return redirect(url_for("auth.login"))

    pending = json.loads(_OAUTH_STATE_PATH.read_text())
    _OAUTH_STATE_PATH.unlink(missing_ok=True)

    state = pending.get("state")
    code_verifier = pending.get("code_verifier")

    flow = Flow.from_client_secrets_file(
        str(settings.gmail_credentials_path),
        scopes=SCOPES,
        state=state,
        redirect_uri=_build_redirect_uri(),
    )
    if code_verifier:
        flow.code_verifier = code_verifier

    try:
        flow.fetch_token(authorization_response=request.url)
    except (ValueError, OSError) as e:
        logger.exception("Authentication failed: %s", e)
        flash("Authentication failed. Please try again.")
        return redirect(url_for("auth.login"))

    creds = flow.credentials
    settings.gmail_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.gmail_token_path.write_text(creds.to_json())

    session["authenticated"] = True
    return redirect(url_for("main.inbox"))


@bp_auth.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
