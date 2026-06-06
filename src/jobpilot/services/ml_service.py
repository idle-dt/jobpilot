"""ML training trigger logic."""

import logging
import multiprocessing
import os
import sqlite3
import time
from pathlib import Path

from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

MANUAL_RETRAIN_TIMEOUT_SECONDS = 60
LOCK_TTL_SECONDS = 300  # 5 minutes — auto-clear stale locks from crashed processes

# Use "spawn" context to avoid inheriting parent's SQLite file descriptors.
# The default "fork" on macOS copies the parent's connection state, causing
# "database is locked" even with WAL mode and busy timeouts.
_spawn_ctx = multiprocessing.get_context("spawn")

_LOCK_DIR = Path.home() / ".jobpilot" / "locks"


def _lock_path(model_type: str) -> Path:
    """Return the lock file path for a model type."""
    return _LOCK_DIR / f"retrain_{model_type}.lock"


def _acquire_lock(model_type: str) -> bool:
    """Try to acquire a lock file atomically.

    Uses O_CREAT | O_EXCL for atomic creation. Stale locks older than
    LOCK_TTL_SECONDS are cleared automatically (handles crashed processes).
    """
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(model_type)
    if lock.exists():
        try:
            age = time.time() - lock.stat().st_mtime
        except FileNotFoundError:
            pass  # Cleared by another process between exists() and stat()
        else:
            if age > LOCK_TTL_SECONDS:
                logger.warning("Clearing stale %s lock (%.0fs old)", model_type, age)
                lock.unlink(missing_ok=True)
            else:
                return False
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock(model_type: str) -> None:
    """Release the lock file for a model type."""
    _lock_path(model_type).unlink(missing_ok=True)


class MLService:
    """Handles ML auto-retraining checks."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def maybe_auto_retrain(self) -> None:
        """Check retrain conditions; spawn subprocess so segfaults don't kill the server."""
        try:
            from jobpilot.classifier.ml_trainer import MLTrainer
            trainer = MLTrainer(self.repo)
            retrain_types = [
                mt for mt in ("noise", "scoring") if trainer.should_retrain(mt)
            ]
            if not retrain_types:
                return
            # Release implicit transactions so the subprocess can write to the DB
            self.repo.commit()
            for model_type in retrain_types:
                if not _acquire_lock(model_type):
                    logger.info("Skipping %s retrain — already running", model_type)
                    continue
                logger.info("Auto-retraining %s model in subprocess", model_type)
                try:
                    p = _spawn_ctx.Process(
                        target=self._retrain_in_subprocess,
                        args=(model_type,),
                        daemon=True,
                    )
                    p.start()
                except OSError:
                    _release_lock(model_type)
                    logger.exception("Failed to spawn %s retrain subprocess", model_type)
        except (
            ValueError, RuntimeError, ImportError, OSError,
            sqlite3.OperationalError,
        ):
            logger.exception("Auto-retrain check failed")

    def run_manual_retrain(self, model_type: str) -> tuple[bool, str]:
        """Run retrain in subprocess with timeout. Returns (success, message)."""
        if not _acquire_lock(model_type):
            return False, "Training already in progress"
        self.repo.commit()
        try:
            p = _spawn_ctx.Process(
                target=self._retrain_in_subprocess,
                args=(model_type,),
            )
            p.start()
        except OSError:
            _release_lock(model_type)
            logger.exception("Failed to spawn %s retrain subprocess", model_type)
            return False, "Training failed"

        p.join(timeout=MANUAL_RETRAIN_TIMEOUT_SECONDS)

        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
            _release_lock(model_type)
            return False, "Training timed out"

        if p.exitcode != 0:
            _release_lock(model_type)
            return False, "Training failed"

        return True, "ok"

    @staticmethod
    def _retrain_in_subprocess(model_type: str) -> None:
        """Run training in isolated subprocess so segfaults don't kill the server."""
        conn = None
        try:
            from jobpilot.classifier.ml_trainer import MLTrainer
            from jobpilot.config import settings
            from jobpilot.storage.database import get_connection
            conn = get_connection(settings.db_path)
            repo = Repository(conn)
            trainer = MLTrainer(repo)
            trainer.train_all(model_type)
        except (
            ValueError, RuntimeError, ImportError, OSError,
            sqlite3.Error,
        ):
            logging.getLogger(__name__).exception(
                "Subprocess retrain failed for %s", model_type,
            )
        finally:
            if conn:
                conn.close()
            _release_lock(model_type)
