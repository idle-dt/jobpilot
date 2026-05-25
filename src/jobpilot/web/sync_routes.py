"""Sync pipeline routes — async launcher, status polling, browser login."""

import logging
import sqlite3
import threading

import google.auth.exceptions
import requests
from flask import Blueprint, jsonify, request

from jobpilot.config import settings
from jobpilot.scraper.browser import ALLOWED_SITES
from jobpilot.storage.database import get_connection
from jobpilot.storage.repository import Repository
from jobpilot.web.app import limiter

logger = logging.getLogger(__name__)

bp_sync = Blueprint("sync", __name__)


@bp_sync.route("/api/sync", methods=["POST"])
@limiter.limit("2 per minute")
def sync_emails():
    """Start async sync pipeline in background thread."""
    from jobpilot.services.sync_state import sync_state

    if not sync_state.start():
        return jsonify({"status": "already_running"})

    thread = threading.Thread(target=_run_sync_background, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@bp_sync.route("/api/sync/status")
@limiter.limit("30 per minute")
def sync_status():
    """Return current sync pipeline state for UI polling."""
    from jobpilot.services.sync_state import sync_state
    return jsonify(sync_state.to_dict())


@bp_sync.route("/api/scraper/login", methods=["POST"])
def scraper_login():
    """Open a visible browser for manual login to a job site."""
    site = request.form.get("site", "").strip().lower()
    if site not in ALLOWED_SITES:
        return jsonify({"status": "error", "message": "Invalid site"}), 400

    def _run_login(site_name: str) -> None:
        from playwright.sync_api import Error as PlaywrightError

        from jobpilot.scraper.browser import BrowserScraper
        conn = None
        try:
            conn = get_connection(settings.db_path)
            conn.execute("PRAGMA busy_timeout=30000")
            repo = Repository(conn)
            scraper = BrowserScraper(headless=False)
            scraper.login(site_name)
            scraper.close()
            repo.set_setting(f"browser_session_{site_name}", "1")
            logger.info("[Sync] browser: %s session saved", site_name)
        except (OSError, ImportError, ValueError, PlaywrightError):
            logger.exception("[Sync] Browser login failed for %s", site_name)
        finally:
            if conn:
                conn.close()

    threading.Thread(target=_run_login, args=(site,), daemon=True).start()
    return jsonify({"status": "ok", "site": site})


def _run_sync_background() -> None:
    """Run the full sync pipeline in a background thread.

    IMPORTANT: This runs outside any Flask request context.
    Must create its own DB connection — never use _repo() or current_app here.
    """
    from jobpilot.services.sync_service import SyncService
    from jobpilot.services.sync_state import sync_state

    conn = None
    try:
        conn = get_connection(settings.db_path)
        conn.execute("PRAGMA busy_timeout=30000")
        repo = Repository(conn)
        result = SyncService(repo).run()
        sync_state.finish(
            new_emails=result.new_emails,
            arbeitnow_jobs=result.arbeitnow_jobs,
        )
    except (ValueError, FileNotFoundError, OSError):
        logger.exception("[Sync] Auth failed")
        sync_state.fail("auth_required")
    except google.auth.exceptions.RefreshError:
        logger.exception("[Sync] Gmail token expired or revoked")
        sync_state.fail("auth_expired")
    except (requests.RequestException, sqlite3.OperationalError, RuntimeError, KeyError):
        logger.exception("[Sync] Pipeline failed")
        sync_state.fail("sync_error")
    except Exception:
        # Thread boundary: uncaught exceptions must update state,
        # otherwise sync_state.running stays True forever.
        logger.exception("[Sync] Unexpected pipeline failure")
        sync_state.fail("sync_error")
    finally:
        if conn:
            conn.close()
