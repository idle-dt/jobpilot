"""Tests for the service layer extracted from the route handlers."""

import sqlite3

from jobpilot.services.inbox_service import (
    DEFAULT_SORT,
    InboxService,
    sort_signals,
)
from jobpilot.services.ml_export_service import MLExportService
from jobpilot.services.settings_service import SettingsService
from jobpilot.storage.models import ExtractedSignal
from jobpilot.storage.repository import Repository


def _insert_review_job(
    db_conn: sqlite3.Connection, title: str, score: float,
    classification: str = "worth_checking",
) -> None:
    """Insert an unlabeled scraped job that qualifies for the review queue."""
    db_conn.execute(
        "INSERT INTO scraped_jobs (source, title, url, score, classification) "
        "VALUES (?,?,?,?,?)",
        ("linkedin", title, f"https://linkedin.com/jobs/view/{title}", score,
         classification),
    )
    db_conn.commit()


# --- InboxService ---

def test_sort_signals_orders_by_priority() -> None:
    """tech_stack sorts before platform; unknown types fall to the end."""
    signals = [
        ExtractedSignal(id=None, email_id="e", signal_type="platform", signal_value="x"),
        ExtractedSignal(id=None, email_id="e", signal_type="tech_stack", signal_value="y"),
        ExtractedSignal(id=None, email_id="e", signal_type="mystery", signal_value="z"),
    ]
    ordered = [s.signal_type for s in sort_signals(signals)]
    assert ordered == ["tech_stack", "platform", "mystery"]


def test_build_review_queue_sorts_by_score(repo: Repository, db_conn) -> None:
    """score_desc puts the highest-scored item first; score_asc reverses it."""
    _insert_review_job(db_conn, "low", 0.2)
    _insert_review_job(db_conn, "high", 0.9)
    service = InboxService(repo)

    desc = service.build_review_queue("score_desc")
    asc = service.build_review_queue("score_asc")

    assert [i["obj"].title for i in desc] == ["high", "low"]
    assert [i["obj"].title for i in asc] == ["low", "high"]


def test_build_review_queue_invalid_sort_falls_back(repo: Repository, db_conn) -> None:
    """An unknown sort key is treated as the default (score_desc)."""
    _insert_review_job(db_conn, "low", 0.2)
    _insert_review_job(db_conn, "high", 0.9)
    service = InboxService(repo)

    assert service.build_review_queue("bogus") == service.build_review_queue(DEFAULT_SORT)


def test_build_review_queue_noise_flag_false_without_predictions(
    repo: Repository, db_conn,
) -> None:
    """With no ML predictions, no item is flagged as noise."""
    _insert_review_job(db_conn, "job", 0.5)
    items = InboxService(repo).build_review_queue()
    assert items and all(item["noise_flag"] is False for item in items)


def test_count_review_totals_arithmetic(repo: Repository, db_conn) -> None:
    """skip_count is the review total minus the worth_checking count."""
    _insert_review_job(db_conn, "wc", 0.8, classification="worth_checking")
    _insert_review_job(db_conn, "noise", 0.1, classification="not_a_job")
    total, worth_checking, skip = InboxService(repo).count_review_totals()
    assert total == 2
    assert worth_checking == 1
    assert skip == 1


# --- SettingsService ---

def test_settings_context_has_expected_keys(repo: Repository) -> None:
    """build_context returns every key the settings template consumes."""
    context = SettingsService(repo).build_context()
    expected = {
        "sync_days", "score_threshold", "prefs", "salary_currency",
        "salary_min", "salary_max", "arbeitnow_enabled", "arbeitnow_visa_only",
        "domain_list", "browser_sessions",
    }
    assert expected <= set(context)


def test_settings_domain_list_dedups_and_flags_active(repo: Repository) -> None:
    """A domain added as a preference appears once and is marked active."""
    repo.insert_preference("monitored_domain", "linkedin.com")  # also a known domain
    domain_list = SettingsService(repo).build_context()["domain_list"]

    linkedin = [d for d in domain_list if d["domain"] == "linkedin.com"]
    assert len(linkedin) == 1  # not duplicated despite being known + a preference
    assert linkedin[0]["active"] is True


# --- MLExportService ---

def test_build_export_shape_on_empty_db(repo: Repository) -> None:
    """An export with no models still has the full top-level structure."""
    export = MLExportService(repo).build_export("scoring")
    assert set(export) == {
        "exported_at", "model_type", "training_data", "algorithms",
        "predictions", "disagreements",
    }
    assert export["model_type"] == "scoring"
    assert export["algorithms"] == {}
    assert export["training_data"]["samples"] == []


def test_build_prediction_entry_detects_disagreement() -> None:
    """A model whose prediction differs from the user label is flagged disagreeing."""
    item = {
        "item_type": "email",
        "item_id": "x",
        "title": "Backend Engineer",
        "user_label": "worth_checking",
        "raw_score": 0.5,
        "predictions": {
            "LR": {"prediction": "skip", "probability": 0.9},
            "RF": {"prediction": "worth_checking", "probability": 0.8},
        },
    }
    entry, disagree = MLExportService._build_prediction_entry(item)
    assert set(entry["ml_predictions"]) == {"LR", "RF"}
    assert disagree == ["LR"]
