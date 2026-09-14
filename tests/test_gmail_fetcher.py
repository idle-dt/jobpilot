"""Tests for partial-tolerant Gmail fetching."""

from typing import Any

from jobpilot.gmail.client import GmailQuotaExhaustedError
from jobpilot.gmail.fetcher import FetchResult, fetch_new_emails
from jobpilot.storage.repository import Repository

_STUB_COUNT = 10
_FAILING_INDEX = 3  # 0-based: the 4th message fails


def _raw_message(msg_id: str) -> dict[str, Any]:
    """Build a minimal raw Gmail message that parse_message can handle."""
    return {
        "id": msg_id,
        "threadId": f"t-{msg_id}",
        "payload": {
            "headers": [
                {"name": "From", "value": "jobs@linkedin.com"},
                {"name": "Subject", "value": f"Python developer role {msg_id}"},
                {"name": "Date", "value": "Mon, 14 Sep 2026 09:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": "SGVsbG8gam9icw=="},  # "Hello jobs"
        },
    }


class _FakeClient:
    """Gmail client stand-in that raises a chosen error on one message."""

    def __init__(self, failure: Exception | None, failing_index: int):
        self.stubs = [{"id": f"m{i}"} for i in range(_STUB_COUNT)]
        self.failure = failure
        self.failing_index = failing_index
        self.fetched: list[str] = []

    def list_messages(self, query: str, max_results: int = 100) -> list[dict]:
        return self.stubs

    def get_message(self, message_id: str) -> dict:
        if self.failure and message_id == f"m{self.failing_index}":
            raise self.failure
        self.fetched.append(message_id)
        return _raw_message(message_id)


def test_quota_exhaustion_truncates_the_batch(repo: Repository) -> None:
    """A quota error on the 4th message stops the loop and reports truncation."""
    client = _FakeClient(GmailQuotaExhaustedError("quota"), _FAILING_INDEX)
    result = fetch_new_emails(client, repo)
    assert result == FetchResult(new_emails=_FAILING_INDEX, truncated=True)


def test_emails_before_the_cutoff_persist(repo: Repository) -> None:
    """Messages stored before a quota cut-off stay in the database."""
    client = _FakeClient(GmailQuotaExhaustedError("quota"), _FAILING_INDEX)
    fetch_new_emails(client, repo)
    for i in range(_FAILING_INDEX):
        assert repo.get_email(f"m{i}") is not None
    assert repo.get_email(f"m{_FAILING_INDEX}") is None


def test_bad_message_is_skipped_not_fatal(repo: Repository) -> None:
    """A single malformed message is skipped; the rest of the batch still processes."""
    client = _FakeClient(ValueError("malformed"), _FAILING_INDEX)
    result = fetch_new_emails(client, repo)
    assert result == FetchResult(new_emails=_STUB_COUNT - 1, truncated=False)
    assert repo.get_email(f"m{_FAILING_INDEX}") is None
    assert repo.get_email(f"m{_STUB_COUNT - 1}") is not None


def test_quota_exhaustion_while_listing_truncates(repo: Repository) -> None:
    """A quota error on the listing call yields an empty truncated result, not a crash."""
    client = _FakeClient(None, _FAILING_INDEX)

    def _boom(query: str, max_results: int = 100) -> list[dict]:
        raise GmailQuotaExhaustedError("quota")

    client.list_messages = _boom
    assert fetch_new_emails(client, repo) == FetchResult(new_emails=0, truncated=True)


def test_already_stored_messages_are_not_recounted(repo: Repository) -> None:
    """A second pass over the same messages reports zero new emails."""
    client = _FakeClient(None, _FAILING_INDEX)
    assert fetch_new_emails(client, repo).new_emails == _STUB_COUNT
    assert fetch_new_emails(client, repo) == FetchResult(new_emails=0, truncated=False)
