"""Data models for JobPilot storage layer."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Email:
    id: str
    thread_id: str
    sender: str
    sender_domain: str
    subject: str
    received_at: datetime
    body_text: str | None = None
    body_html: str | None = None
    fetched_at: datetime | None = None
    platform: str | None = None
    is_job_related: bool = True
    raw_score: float | None = None
    ml_score: float | None = None
    final_classification: str | None = None
    confidence: float | None = None
    processed: bool = False
    origin_url: str | None = None


@dataclass
class ExtractedSignal:
    id: int | None
    email_id: str
    signal_type: str
    signal_value: str
    confidence: float = 1.0
    created_at: datetime | None = None


@dataclass
class UserFeedback:
    id: int | None
    email_id: str
    label: str
    feedback_at: datetime | None = None
    notes: str | None = None


@dataclass
class ModelVersion:
    id: int | None
    version: int
    training_samples: int
    model_blob: bytes
    trained_at: datetime | None = None
    accuracy: float | None = None
    precision_score: float | None = None
    recall_score: float | None = None
    f1_score: float | None = None
    feature_names: str | None = None
    is_active: bool = False


@dataclass
class PlatformPattern:
    id: int | None
    platform_name: str
    sender_pattern: str | None = None
    subject_pattern: str | None = None
    domain_pattern: str | None = None
    is_active: bool = True


@dataclass
class ScrapedJob:
    id: int | None
    source: str
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    salary: str | None = None
    posted_date: str | None = None
    remote: bool = False
    scraped_at: str | None = None
    score: float | None = None
    ml_score: float | None = None
    classification: str = "pending"
    user_label: str | None = None
    labeled_at: str | None = None
    email_id: str | None = None
    expired: bool = False
    description: str | None = None
    scrape_attempted: bool = False


@dataclass
class Application:
    id: int | None
    company: str
    role_title: str
    status: str = "applied"
    email_id: str | None = None
    scraped_job_id: int | None = None
    location: str | None = None
    salary_range: str | None = None
    job_url: str | None = None
    platform: str | None = None
    track: str | None = None
    saved_at: str | None = None
    applied_at: str | None = None
    last_status_change: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    notes: str | None = None
    cover_letter_track: str | None = None
    cv_version: str | None = None
    offer_salary: str | None = None
    offer_currency: str | None = None
    offer_equity: str | None = None
    offer_relocation_package: str | None = None
    offer_notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class ApplicationStatusHistory:
    id: int | None
    application_id: int
    to_status: str
    from_status: str | None = None
    changed_at: str | None = None
    notes: str | None = None
