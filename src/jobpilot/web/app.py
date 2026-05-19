"""Flask application factory."""

import logging
import logging.handlers
import os
from pathlib import Path

from flask import Flask, g, redirect, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from jobpilot.config import settings
from jobpilot.gmail.auth import GmailAuth
from jobpilot.services.classification_service import ClassificationService
from jobpilot.storage.database import init_db
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

_PUBLIC_ENDPOINTS = ("/auth/", "/static/")

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["60 per minute"],
)


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

    # File logging for sync pipeline
    log_dir = Path.home() / ".jobpilot"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "jobpilot.log", maxBytes=2_000_000, backupCount=3,
    )
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger("jobpilot").addHandler(fh)
    logging.getLogger("jobpilot").setLevel(logging.INFO)

    csrf.init_app(app)
    limiter.init_app(app)

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
    from jobpilot.web.sync_routes import bp_sync
    from jobpilot.web.tracker_routes import bp_tracker
    app.register_blueprint(bp)
    app.register_blueprint(bp_auth)
    app.register_blueprint(bp_sync)
    app.register_blueprint(bp_tracker)

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

    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        from flask import jsonify as _jsonify
        return _jsonify({"status": "error", "message": "Too many requests, please wait"}), 429

    return app
