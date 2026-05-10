"""User preference data access."""

import sqlite3

from jobpilot.storage.models import UserPreference


class PreferenceRepository:
    """CRUD operations for user preferences."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_preference(self, category: str, value: str, extra: str | None = None) -> int | None:
        """Insert a preference. Returns id if inserted, None if duplicate."""
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO user_preferences (category, value, extra) VALUES (?, ?, ?)",
            (category, value, extra),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            return None
        return cursor.lastrowid

    def delete_preference(self, category: str, value: str) -> bool:
        """Delete a preference. Returns True if deleted."""
        cursor = self.conn.execute(
            "DELETE FROM user_preferences WHERE category = ? AND value = ?",
            (category, value),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_preferences(self, category: str) -> list[UserPreference]:
        """Get all preferences for a category."""
        rows = self.conn.execute(
            "SELECT * FROM user_preferences WHERE category = ? ORDER BY value",
            (category,),
        ).fetchall()
        return [
            UserPreference(
                id=r["id"], category=r["category"], value=r["value"],
                extra=r["extra"], created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_all_preferences(self) -> dict[str, list[UserPreference]]:
        """Get all preferences grouped by category."""
        rows = self.conn.execute(
            "SELECT * FROM user_preferences ORDER BY category, value"
        ).fetchall()
        result: dict[str, list[UserPreference]] = {}
        for r in rows:
            pref = UserPreference(
                id=r["id"], category=r["category"], value=r["value"],
                extra=r["extra"], created_at=r["created_at"],
            )
            result.setdefault(r["category"], []).append(pref)
        return result

    def get_active_domains(self) -> list[str]:
        """Get all monitored domain values."""
        rows = self.conn.execute(
            "SELECT value FROM user_preferences WHERE category = 'monitored_domain' ORDER BY value"
        ).fetchall()
        return [r["value"] for r in rows]

    def count_preferences(self) -> int:
        """Count total preferences."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM user_preferences").fetchone()
        return row["cnt"]
