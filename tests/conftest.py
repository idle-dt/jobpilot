"""Shared test fixtures."""

import sqlite3
from pathlib import Path

import pytest

from jobpilot.storage.database import init_db
from jobpilot.storage.repository import Repository


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
