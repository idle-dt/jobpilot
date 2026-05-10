"""Settings key-value store data access."""

import sqlite3


class SettingsRepository:
    """CRUD operations for application settings."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Get a setting value by key, with optional default."""
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return row["value"]
        return default

    def set_setting(self, key: str, value: str) -> None:
        """Set a setting value (insert or replace)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()
