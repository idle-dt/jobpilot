"""Shared test fixtures."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

from jobpilot.storage.database import init_db
from jobpilot.storage.repository import Repository
from jobpilot.web.app import create_app


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create an in-memory-like temp database for testing."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def repo(db_conn: sqlite3.Connection) -> Repository:
    """Repository backed by a temporary database."""
    return Repository(db_conn)


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Flask application configured for testing."""
    with patch("jobpilot.web.app.settings") as mock_settings:
        mock_settings.secret_key = "test-secret-key"
        mock_settings.debug = False
        mock_settings.db_path = tmp_path / "test.db"
        mock_settings.score_threshold = 0.6
        mock_settings.scrape_confidence_threshold = 0.7
        mock_settings.min_training_samples = 20
        mock_settings.gmail_credentials_path = ""
        mock_settings.gmail_token_path = ""
        test_app = create_app()

    test_app.config["TESTING"] = True
    test_app.config["WTF_CSRF_ENABLED"] = False
    return test_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Flask test client with CSRF disabled."""
    return app.test_client()
