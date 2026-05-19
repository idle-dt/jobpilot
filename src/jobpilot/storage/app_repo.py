"""Application data access."""

import re
import sqlite3

from jobpilot.storage.models import Application, ApplicationStatusHistory

_UPDATABLE_COLUMNS = frozenset({
    "company", "role_title", "location", "remote", "salary_range", "job_url",
    "platform", "notes", "contact_name", "contact_email", "offer_salary",
    "offer_currency", "offer_equity", "offer_relocation_package", "offer_notes",
})

# Safety: column names are validated against _UPDATABLE_COLUMNS AND this regex
# before interpolation into SQL. Both guards must pass.
_COLUMN_NAME_RE = re.compile(r"^[a-z_]+$")


class ApplicationRepository:
    """CRUD operations for job applications and status history."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_application(self, app: Application) -> int:
        """Insert a new application. Returns the new ID."""
        cursor = self.conn.execute(
            """INSERT INTO applications
            (email_id, scraped_job_id, company, role_title, location, remote,
             salary_range, job_url, platform, status, contact_name, contact_email, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                app.email_id, app.scraped_job_id, app.company, app.role_title,
                app.location, app.remote, app.salary_range, app.job_url,
                app.platform, app.status, app.contact_name, app.contact_email,
                app.notes,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_application(self, app_id: int) -> Application | None:
        """Get a single application by ID."""
        row = self.conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_application(row)

    def get_applications_by_status(self, status: str | None = None) -> list[Application]:
        """Get applications, optionally filtered by status."""
        if status:
            rows = self.conn.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY last_status_change DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM applications ORDER BY last_status_change DESC"
            ).fetchall()
        return [self._row_to_application(r) for r in rows]

    def update_application_status(
        self, app_id: int, new_status: str, notes: str | None = None,
    ) -> None:
        """Update application status and record history."""
        current = self.get_application(app_id)
        if not current:
            return
        self.conn.execute(
            """UPDATE applications SET status = ?, last_status_change = datetime('now'),
            updated_at = datetime('now') WHERE id = ?""",
            (new_status, app_id),
        )
        self.conn.execute(
            """INSERT INTO application_status_history
            (application_id, from_status, to_status, notes)
            VALUES (?, ?, ?, ?)""",
            (app_id, current.status, new_status, notes),
        )
        self.conn.commit()

    def get_application_history(self, app_id: int) -> list[ApplicationStatusHistory]:
        """Get status change history for an application."""
        rows = self.conn.execute(
            "SELECT * FROM application_status_history WHERE application_id = ? ORDER BY changed_at",
            (app_id,),
        ).fetchall()
        return [
            ApplicationStatusHistory(
                id=r["id"], application_id=r["application_id"],
                from_status=r["from_status"], to_status=r["to_status"],
                changed_at=r["changed_at"], notes=r["notes"],
            )
            for r in rows
        ]

    def count_applications_by_status(self) -> dict[str, int]:
        """Count applications grouped by status."""
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    def get_application_by_scraped_job_id(self, scraped_job_id: int) -> Application | None:
        """Get an application linked to a scraped job."""
        row = self.conn.execute(
            "SELECT * FROM applications WHERE scraped_job_id = ? LIMIT 1",
            (scraped_job_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_application(row)

    def update_application(self, app_id: int, **fields: str | None) -> bool:
        """Partial update of application fields. Returns True if updated."""
        safe = {
            k: v for k, v in fields.items()
            if k in _UPDATABLE_COLUMNS and _COLUMN_NAME_RE.match(k)
        }
        if not safe:
            return False
        sets = ", ".join(f"{col} = ?" for col in safe)
        sql = f"UPDATE applications SET {sets}, updated_at = datetime('now') WHERE id = ?"  # noqa: S608
        self.conn.execute(sql, [*safe.values(), app_id])
        self.conn.commit()
        return True

    def delete_application(self, app_id: int) -> None:
        """Delete an application and its status history atomically."""
        try:
            self.conn.execute(
                "DELETE FROM application_status_history WHERE application_id = ?",
                (app_id,),
            )
            self.conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def _row_to_application(self, row: sqlite3.Row) -> Application:
        """Convert a database row to an Application model."""
        return Application(
            id=row["id"], company=row["company"], role_title=row["role_title"],
            status=row["status"], email_id=row["email_id"],
            scraped_job_id=row["scraped_job_id"], location=row["location"],
            remote=bool(row["remote"]),
            salary_range=row["salary_range"], job_url=row["job_url"],
            platform=row["platform"], applied_at=row["applied_at"],
            last_status_change=row["last_status_change"],
            contact_name=row["contact_name"], contact_email=row["contact_email"],
            notes=row["notes"], offer_salary=row["offer_salary"],
            offer_currency=row["offer_currency"], offer_equity=row["offer_equity"],
            offer_relocation_package=row["offer_relocation_package"],
            offer_notes=row["offer_notes"], created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
