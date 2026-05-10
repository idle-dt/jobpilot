"""ML training trigger logic."""

import logging

from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)


class MLService:
    """Handles ML auto-retraining checks."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def maybe_auto_retrain(self) -> None:
        """Check if conditions are met for automatic retraining after feedback."""
        try:
            from jobpilot.classifier.ml_trainer import MLTrainer
            trainer = MLTrainer(self.repo)
            for model_type in ("noise", "scoring"):
                if trainer.should_retrain(model_type):
                    logger.info("Auto-retraining %s model", model_type)
                    trainer.train_all(model_type)
        except (ValueError, RuntimeError, ImportError, OSError):
            logger.exception("Auto-retrain check failed")
