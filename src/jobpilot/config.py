"""Application configuration via pydantic-settings."""

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_SECRET_KEY_PATH = Path.home() / ".jobpilot" / ".secret_key"


def _get_or_create_secret_key() -> str:
    """Return a stable secret key, generating and persisting one if needed."""
    if _SECRET_KEY_PATH.exists():
        return _SECRET_KEY_PATH.read_text().strip()
    _SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    _SECRET_KEY_PATH.write_text(key)
    return key


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JOBPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Paths
    db_path: Path = Path.home() / ".jobpilot" / "jobpilot.db"
    gmail_credentials_path: Path = Path.home() / ".jobpilot" / "credentials.json"
    gmail_token_path: Path = Path.home() / ".jobpilot" / "token.json"

    # Server
    server_host: str = "127.0.0.1"
    server_port: int = 5050
    secret_key: str = _get_or_create_secret_key()
    debug: bool = False

    # Logging
    log_level: str = "INFO"

    # Classification
    score_threshold: float = 0.6
    confidence_auto_threshold: float = 0.8
    min_training_samples: int = 30
    retrain_after_n_labels: int = 10

    # Scoring weights
    weight_tech_match: float = 0.35
    weight_location_match: float = 0.25
    weight_seniority_match: float = 0.15
    weight_salary_match: float = 0.10
    weight_negative_signals: float = 0.15

    # Scheduler
    email_fetch_interval_minutes: int = 15
    scrape_hour: int = 8
    scrape_minute: int = 0

    def ensure_dirs(self) -> None:
        """Create necessary directories if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
