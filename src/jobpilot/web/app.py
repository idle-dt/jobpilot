"""Flask application factory."""

import logging
import os

from flask import Flask, g, redirect, request, url_for

from jobpilot.config import settings
from jobpilot.gmail.auth import GmailAuth
from jobpilot.services.classification_service import ClassificationService
from jobpilot.storage.database import init_db
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

_PUBLIC_ENDPOINTS = ("/auth/", "/static/")


def create_app() -> Flask:
    """Create and configure the Flask application."""
    web_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        static_folder=os.path.join(web_dir, "static"),
        template_folder=os.path.join(web_dir, "templates"),
    )
    app.config["SECRET_KEY"] = settings.secret_key
    app.debug = settings.debug

    # Initialize database and repository
    conn = init_db(settings.db_path)
    repo = Repository(conn)
    app.config["repo"] = repo

    # Classify unprocessed emails and score pending jobs on startup.
    # In debug mode, skip in the reloader parent process to avoid DB lock
    # conflicts — the child (actual server) process will run these.
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        svc = ClassificationService(repo)
        svc.classify_unprocessed()
        svc.parse_existing_digests()
        svc.score_pending_jobs()

    # Register custom filters
    from jobpilot.web.filters import highlight_signals
    app.jinja_env.filters["highlight_signals"] = highlight_signals

    # Register routes
    from jobpilot.web.auth_routes import bp_auth
    from jobpilot.web.routes import bp
    app.register_blueprint(bp)
    app.register_blueprint(bp_auth)

    # Auth gate: redirect unauthenticated users to login
    @app.before_request
    def require_auth():
        if any(request.path.startswith(p) for p in _PUBLIC_ENDPOINTS):
            return None
        try:
            auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)
            g.authenticated = auth.is_authenticated()
        except Exception:
            g.authenticated = False
        if not g.authenticated:
            return redirect(url_for("auth.login"))

    # Inject common template variables
    @app.context_processor
    def inject_globals():
        authenticated = getattr(g, "authenticated", False)
        last_sync = repo.get_last_sync_time() if authenticated else None
        return {"authenticated": authenticated, "last_sync": last_sync}

    return app
