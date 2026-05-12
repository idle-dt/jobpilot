"""ML training trigger logic."""

import logging
import multiprocessing
import sqlite3

from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

MANUAL_RETRAIN_TIMEOUT_SECONDS = 60

# Use "spawn" context to avoid inheriting parent's SQLite file descriptors.
# The default "fork" on macOS copies the parent's connection state, causing
# "database is locked" even with WAL mode and busy timeouts.
_spawn_ctx = multiprocessing.get_context("spawn")


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
                logger.info("Auto-retraining %s model in subprocess", model_type)
                p = _spawn_ctx.Process(
                    target=self._retrain_in_subprocess,
                    args=(model_type,),
                    daemon=True,
                )
                p.start()
        except (
            ValueError, RuntimeError, ImportError, OSError,
            sqlite3.OperationalError,
        ):
            logger.exception("Auto-retrain check failed")

    def run_manual_retrain(self, model_type: str) -> tuple[bool, str]:
        """Run retrain in subprocess with timeout. Returns (success, message)."""
        self.repo.commit()
        p = _spawn_ctx.Process(
            target=self._retrain_in_subprocess,
            args=(model_type,),
        )
        p.start()
        p.join(timeout=MANUAL_RETRAIN_TIMEOUT_SECONDS)

        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
            return False, "Training timed out"

        if p.exitcode != 0:
            return False, "Training failed"

        return True, "ok"

    @staticmethod
    def _retrain_in_subprocess(model_type: str) -> None:
        """Run training in isolated subprocess so segfaults don't kill the server."""
        conn = None
        try:
            from jobpilot.classifier.ml_trainer import MLTrainer
            from jobpilot.config import settings
            conn = sqlite3.connect(
                str(settings.db_path), timeout=30, check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
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
