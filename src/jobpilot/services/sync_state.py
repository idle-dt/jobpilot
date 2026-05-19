"""Thread-safe global state for the sync pipeline."""

import threading
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SyncState:
    """Thread-safe sync pipeline state, survives page navigation."""

    running: bool = False
    step: str = ""
    detail: str = ""
    current: int = 0
    total: int = 0
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    new_emails: int = 0
    arbeitnow_jobs: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def start(self) -> bool:
        """Try to start sync. Returns False if already running."""
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.step = "starting"
            self.detail = ""
            self.current = 0
            self.total = 0
            self.error = None
            self.started_at = datetime.now().isoformat()
            self.finished_at = None
            self.new_emails = 0
            self.arbeitnow_jobs = 0
            return True

    def update(self, step: str, detail: str = "", current: int = 0, total: int = 0) -> None:
        """Update progress atomically."""
        with self._lock:
            self.step = step
            self.detail = detail
            self.current = current
            self.total = total

    def finish(self, new_emails: int = 0, arbeitnow_jobs: int = 0) -> None:
        """Mark sync as complete."""
        with self._lock:
            self.running = False
            self.step = "done"
            self.detail = ""
            self.current = 0
            self.total = 0
            self.finished_at = datetime.now().isoformat()
            self.new_emails = new_emails
            self.arbeitnow_jobs = arbeitnow_jobs

    def fail(self, error: str) -> None:
        """Mark sync as failed."""
        with self._lock:
            self.running = False
            self.step = "error"
            self.detail = ""
            self.current = 0
            self.total = 0
            self.error = error
            self.finished_at = datetime.now().isoformat()

    def to_dict(self) -> dict[str, bool | str | int | None]:
        """Return state as JSON-serializable dict."""
        with self._lock:
            return {
                "running": self.running,
                "step": self.step,
                "detail": self.detail,
                "current": self.current,
                "total": self.total,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "new_emails": self.new_emails,
                "arbeitnow_jobs": self.arbeitnow_jobs,
            }


# Global instance — shared between routes and sync thread
sync_state = SyncState()
