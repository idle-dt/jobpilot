"""Data models for JobPilot storage layer."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Email:
    """A fetched email from a job platform.

    Classification values: 'worth_checking', 'skip', or None (unclassified).
    Platform values: 'linkedin', 'wellfound', 'glassdoor', etc.
    """
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
    """A signal extracted from an email (tech stack, location, salary, etc).

    Signal types: 'tech_stack', 'location', 'salary', 'job_title',
    'seniority', 'negative', 'platform'.
    """
    id: int | None
    email_id: str
    signal_type: str
    signal_value: str
    confidence: float = 1.0
    created_at: datetime | None = None


@dataclass
class UserFeedback:
    """User-provided label for an email classification.

    Label values: 'worth_checking', 'skip', 'not_a_job'.
    """
    id: int | None
    email_id: str
    label: str
    feedback_at: datetime | None = None
    notes: str | None = None


@dataclass
class ModelVersion:
    """A trained ML model version with metrics and serialized weights.

    Model types: 'noise' (job vs non-job), 'scoring' (worth_checking vs skip).
    Algorithm values: 'LR', 'RF', 'GBC', 'SVM'.
    """
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
    model_type: str = "scoring"
    algorithm: str = "LR"
    train_accuracy: float | None = None


@dataclass
class MLPrediction:
    """A model's prediction for a specific item.

    Item types: 'email', 'scraped_job'.
    """
    id: int | None
    model_version_id: int
    item_type: str
    item_id: str
    prediction: str
    probability: float | None = None
    predicted_at: str | None = None


@dataclass
class PlatformPattern:
    """Pattern matching rule for detecting email platforms."""
    id: int | None
    platform_name: str
    sender_pattern: str | None = None
    subject_pattern: str | None = None
    domain_pattern: str | None = None
    is_active: bool = True


@dataclass
class ScrapedJob:
    """A job posting extracted from a digest email or job board.

    Classification values: 'pending', 'worth_checking', 'skip'.
    User label values: 'worth_checking', 'skip', 'not_a_job', or None.
    """
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
    matched_signals: str | None = None


@dataclass
class Application:
    """A tracked job application with status history.

    Status values: 'saved', 'applied', 'screening', 'technical',
    'onsite', 'offer', 'accepted', 'rejected', 'withdrawn', 'no_response'.
    """
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
    applied_at: str | None = None
    last_status_change: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    notes: str | None = None
    offer_salary: str | None = None
    offer_currency: str | None = None
    offer_equity: str | None = None
    offer_relocation_package: str | None = None
    offer_notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class UserPreference:
    """A user preference tag in a specific category.

    Categories: 'tech_keyword_primary', 'tech_keyword_secondary', 'job_title',
    'seniority_wanted', 'seniority_unwanted', 'location_primary',
    'location_secondary', 'location_negative', 'negative_signal',
    'monitored_domain'.
    """
    id: int | None
    category: str
    value: str
    extra: str | None = None
    created_at: str | None = None


@dataclass
class ApplicationStatusHistory:
    """Audit trail entry for application status changes."""
    id: int | None
    application_id: int
    to_status: str
    from_status: str | None = None
    changed_at: str | None = None
    notes: str | None = None
