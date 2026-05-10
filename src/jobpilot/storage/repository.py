"""Unified data access — delegates to focused repositories."""

import sqlite3

from jobpilot.storage.app_repo import ApplicationRepository
from jobpilot.storage.email_repo import EmailRepository
from jobpilot.storage.job_repo import JobRepository
from jobpilot.storage.ml_repo import MLRepository
from jobpilot.storage.models import (
    Application,
    Email,
    ExtractedSignal,
    MLPrediction,
    ModelVersion,
    ScrapedJob,
    UserFeedback,
)
from jobpilot.storage.preference_repo import PreferenceRepository
from jobpilot.storage.settings_repo import SettingsRepository
from jobpilot.storage.stats_repo import StatsRepository


class Repository:
    """Data access layer for JobPilot — facade over focused repositories."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.emails = EmailRepository(conn)
        self.jobs = JobRepository(conn)
        self.apps = ApplicationRepository(conn)
        self.ml = MLRepository(conn)
        self.preferences = PreferenceRepository(conn)
        self.stats = StatsRepository(conn)
        self.settings = SettingsRepository(conn)

    # --- Email delegation ---

    def insert_email(self, email: Email) -> None:
        return self.emails.insert_email(email)

    def get_email(self, email_id: str) -> Email | None:
        return self.emails.get_email(email_id)

    def get_emails_for_review(self, limit: int = 20) -> list[Email]:
        return self.emails.get_emails_for_review(limit)

    def get_emails_classified(
        self, classification: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[Email]:
        return self.emails.get_emails_classified(
            classification, limit, offset,
        )

    def update_email_scores(
        self, email_id: str, raw_score: float,
        ml_score: float | None, classification: str,
        confidence: float | None,
    ) -> None:
        return self.emails.update_email_scores(
            email_id, raw_score, ml_score, classification, confidence,
        )

    def update_email_origin_url(
        self, email_id: str, origin_url: str,
    ) -> None:
        return self.emails.update_email_origin_url(email_id, origin_url)

    def get_unprocessed_emails(self) -> list[dict]:
        return self.emails.get_unprocessed_emails()

    def get_emails_needing_origin_url(self) -> list[Email]:
        return self.emails.get_emails_needing_origin_url()

    def get_all_processed_emails(self) -> list[dict]:
        return self.emails.get_all_processed_emails()

    def _row_to_email(self, row) -> Email:
        return self.emails._row_to_email(row)

    # --- Signal delegation ---

    def insert_signal(self, signal: ExtractedSignal) -> None:
        return self.emails.insert_signal(signal)

    def get_signals_for_email(
        self, email_id: str,
    ) -> list[ExtractedSignal]:
        return self.emails.get_signals_for_email(email_id)

    # --- Feedback delegation ---

    def insert_feedback(self, feedback: UserFeedback) -> None:
        return self.emails.insert_feedback(feedback)

    def get_all_feedback(self) -> list[UserFeedback]:
        return self.emails.get_all_feedback()

    def delete_feedback(self, email_id: str) -> None:
        return self.emails.delete_feedback(email_id)

    def count_feedback(self) -> int:
        return self.emails.count_feedback()

    # --- Job delegation ---

    def insert_scraped_job(self, job: ScrapedJob) -> bool:
        return self.jobs.insert_scraped_job(job)

    def get_scraped_jobs_for_review(
        self, limit: int = 20,
    ) -> list[ScrapedJob]:
        return self.jobs.get_scraped_jobs_for_review(limit)

    def update_scraped_job_label(
        self, job_id: int, label: str | None,
    ) -> None:
        return self.jobs.update_scraped_job_label(job_id, label)

    def update_scraped_job_scores(
        self, job_id: int, score: float,
        ml_score: float | None, classification: str,
    ) -> None:
        return self.jobs.update_scraped_job_scores(
            job_id, score, ml_score, classification,
        )

    def update_scraped_job_description(
        self, job_id: int, description: str,
    ) -> None:
        return self.jobs.update_scraped_job_description(
            job_id, description,
        )

    def mark_scrape_attempted(self, job_id: int) -> None:
        return self.jobs.mark_scrape_attempted(job_id)

    def get_jobs_needing_scrape(
        self, score_threshold: float, confidence_threshold: float,
    ) -> list[ScrapedJob]:
        return self.jobs.get_jobs_needing_scrape(
            score_threshold, confidence_threshold,
        )

    def get_email_ids_with_extracted_jobs(self) -> set[str]:
        return self.jobs.get_email_ids_with_extracted_jobs()

    def toggle_scraped_job_expired(self, job_id: int) -> bool:
        return self.jobs.toggle_scraped_job_expired(job_id)

    def delete_scraped_jobs_for_email(self, email_id: str) -> int:
        return self.jobs.delete_scraped_jobs_for_email(email_id)

    def count_scraped_jobs_for_email(self, email_id) -> int:
        return self.jobs.count_scraped_jobs_for_email(email_id)

    def get_pending_scraped_jobs(self) -> list[dict]:
        return self.jobs.get_pending_scraped_jobs()

    def get_unlabeled_scraped_jobs(self) -> list[dict]:
        return self.jobs.get_unlabeled_scraped_jobs()

    def get_all_scraped_jobs(self) -> list[dict]:
        return self.jobs.get_all_scraped_jobs()

    # --- Application delegation ---

    def insert_application(self, app: Application) -> int:
        return self.apps.insert_application(app)

    def get_application(self, app_id: int) -> Application | None:
        return self.apps.get_application(app_id)

    def get_applications_by_status(
        self, status: str | None = None,
    ) -> list[Application]:
        return self.apps.get_applications_by_status(status)

    def update_application_status(
        self, app_id: int, new_status: str,
        notes: str | None = None,
    ) -> None:
        return self.apps.update_application_status(
            app_id, new_status, notes,
        )

    def get_application_history(self, app_id: int):
        return self.apps.get_application_history(app_id)

    def count_applications_by_status(self) -> dict[str, int]:
        return self.apps.count_applications_by_status()

    # --- Preference delegation ---

    def insert_preference(
        self, category: str, value: str,
        extra: str | None = None,
    ) -> int | None:
        return self.preferences.insert_preference(
            category, value, extra,
        )

    def delete_preference(
        self, category: str, value: str,
    ) -> bool:
        return self.preferences.delete_preference(category, value)

    def get_preferences(self, category: str):
        return self.preferences.get_preferences(category)

    def get_all_preferences(self):
        return self.preferences.get_all_preferences()

    def get_active_domains(self) -> list[str]:
        return self.preferences.get_active_domains()

    def count_preferences(self) -> int:
        return self.preferences.count_preferences()

    # --- ML delegation ---

    def insert_model_version(self, mv: ModelVersion) -> int:
        return self.ml.insert_model_version(mv)

    def get_model_versions_by_type(
        self, model_type: str,
    ) -> list[ModelVersion]:
        return self.ml.get_model_versions_by_type(model_type)

    def get_active_model(
        self, model_type: str,
    ) -> ModelVersion | None:
        return self.ml.get_active_model(model_type)

    def get_model_version(
        self, model_id: int,
    ) -> ModelVersion | None:
        return self.ml.get_model_version(model_id)

    def activate_model(
        self, model_type: str, algorithm: str,
    ) -> None:
        return self.ml.activate_model(model_type, algorithm)

    def activate_model_by_id(
        self, model_id: int, model_type: str,
    ) -> None:
        return self.ml.activate_model_by_id(model_id, model_type)

    def delete_model_versions_by_type(
        self, model_type: str,
    ) -> None:
        return self.ml.delete_model_versions_by_type(model_type)

    def get_next_version(self, model_type: str) -> int:
        return self.ml.get_next_version(model_type)

    def invalidate_active_models(self) -> int:
        return self.ml.invalidate_active_models()

    def insert_predictions(
        self, predictions: list[MLPrediction],
    ) -> None:
        return self.ml.insert_predictions(predictions)

    def get_predictions_for_items(
        self, item_type: str, item_ids: list[str],
    ) -> dict[str, list[dict]]:
        return self.ml.get_predictions_for_items(
            item_type, item_ids,
        )

    def delete_predictions_for_model(
        self, model_version_id: int,
    ) -> None:
        return self.ml.delete_predictions_for_model(model_version_id)

    def get_noise_training_data(self) -> list[dict]:
        return self.ml.get_noise_training_data()

    def get_scoring_training_data(self) -> list[dict]:
        return self.ml.get_scoring_training_data()

    def get_last_training_time(
        self, model_type: str,
    ) -> str | None:
        return self.ml.get_last_training_time(model_type)

    def count_labels_since(
        self, since_timestamp: str | None,
    ) -> int:
        return self.ml.count_labels_since(since_timestamp)

    def get_recent_predictions_comparison(
        self, limit: int = 20,
    ) -> list[dict]:
        return self.ml.get_recent_predictions_comparison(limit)

    # --- Settings delegation ---

    def get_setting(
        self, key: str, default: str | None = None,
    ) -> str | None:
        return self.settings.get_setting(key, default)

    def set_setting(self, key: str, value: str) -> None:
        return self.settings.set_setting(key, value)

    # --- Stats delegation ---

    def get_email_stats(self) -> dict:
        return self.stats.get_email_stats()

    def get_last_sync_time(self):
        return self.stats.get_last_sync_time()

    def get_dashboard_stats(
        self, score_threshold: float = 0.6,
    ) -> dict:
        return self.stats.get_dashboard_stats(score_threshold)
