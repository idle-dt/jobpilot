"""ML training trigger logic."""

import logging
import multiprocessing

from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

MANUAL_RETRAIN_TIMEOUT_SECONDS = 60


class MLService:
    """Handles ML auto-retraining checks."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def maybe_auto_retrain(self) -> None:
        """Check retrain conditions; spawn subprocess so segfaults don't kill the server."""
        try:
            from jobpilot.classifier.ml_trainer import MLTrainer
            trainer = MLTrainer(self.repo)
            for model_type in ("noise", "scoring"):
                if trainer.should_retrain(model_type):
                    logger.info("Auto-retraining %s model in subprocess", model_type)
                    p = multiprocessing.Process(
                        target=self._retrain_in_subprocess,
                        args=(model_type,),
                        daemon=True,
                    )
                    p.start()
        except (ValueError, RuntimeError, ImportError, OSError):
            logger.exception("Auto-retrain check failed")

    @staticmethod
    def _retrain_in_subprocess(model_type: str) -> None:
        """Run training in isolated subprocess so segfaults don't kill the server."""
        try:
            from jobpilot.classifier.ml_trainer import MLTrainer
            from jobpilot.config import settings
            from jobpilot.storage.db import init_db
            conn = init_db(settings.db_path)
            repo = Repository(conn)
            trainer = MLTrainer(repo)
            trainer.train_all(model_type)
        except Exception:
            logging.getLogger(__name__).exception(
                "Subprocess retrain failed for %s", model_type,
            )
