"""Tests for quota-resilient Gmail fetching."""

from typing import Any

from jobpilot.gmail.client import GmailQuotaExhaustedError
from jobpilot.gmail.fetcher import _MAX_QUOTA_WAITS, FetchResult, fetch_new_emails
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
    """Gmail client stand-in that fails a chosen message a set number of times."""

    def __init__(self, failure: Exception | None, failing_index: int, fail_times: int = 10**6):
        self.stubs = [{"id": f"m{i}"} for i in range(_STUB_COUNT)]
        self.failure = failure
        self.failing_index = failing_index
        self.fail_times = fail_times
        self.failures_raised = 0
        self.fetched: list[str] = []

    def list_messages(self, query: str, max_results: int = 100) -> list[dict]:
        return self.stubs

    def get_message(self, message_id: str) -> dict:
        if (
            self.failure
            and message_id == f"m{self.failing_index}"
            and self.failures_raised < self.fail_times
        ):
            self.failures_raised += 1
            raise self.failure
        self.fetched.append(message_id)
        return _raw_message(message_id)


def _fetch(
    client: _FakeClient, repo: Repository, sleeps: list[float] | None = None,
) -> FetchResult:
    """Run a fetch with the quota wait stubbed out so tests never really sleep."""
    record = sleeps.append if sleeps is not None else (lambda _: None)
    return fetch_new_emails(client, repo, sleep=record)


def test_quota_pause_then_resume_completes_the_batch(repo: Repository) -> None:
    """A single quota hit pauses, resumes, and still handles every message."""
    sleeps: list[float] = []
    client = _FakeClient(GmailQuotaExhaustedError("quota"), _FAILING_INDEX, fail_times=1)
    result = _fetch(client, repo, sleeps)
    assert result == FetchResult(
        new_emails=_STUB_COUNT, truncated=False, processed=_STUB_COUNT, total=_STUB_COUNT,
    )
    assert len(sleeps) == 1  # exactly one quota window waited out
    for i in range(_STUB_COUNT):
        assert repo.get_email(f"m{i}") is not None


def test_persistent_quota_truncates_after_the_wait_cap(repo: Repository) -> None:
    """When the quota never recovers, the run reports truncation instead of hanging."""
    sleeps: list[float] = []
    client = _FakeClient(GmailQuotaExhaustedError("quota"), _FAILING_INDEX)
    result = _fetch(client, repo, sleeps)
    assert result == FetchResult(
        new_emails=_FAILING_INDEX, truncated=True,
        processed=_FAILING_INDEX, total=_STUB_COUNT,
    )
    assert len(sleeps) == _MAX_QUOTA_WAITS  # bounded, not unbounded


def test_quota_wait_reports_progress(repo: Repository) -> None:
    """The wait callback reports how far the fetch got, for the UI to display."""
    reported: list[tuple[int, int]] = []
    client = _FakeClient(GmailQuotaExhaustedError("quota"), _FAILING_INDEX, fail_times=1)
    fetch_new_emails(
        client, repo, sleep=lambda _: None,
        on_quota_wait=lambda done, total: reported.append((done, total)),
    )
    assert reported == [(_FAILING_INDEX, _STUB_COUNT)]


def test_emails_before_the_cutoff_persist(repo: Repository) -> None:
    """Messages stored before a quota cut-off stay in the database."""
    client = _FakeClient(GmailQuotaExhaustedError("quota"), _FAILING_INDEX)
    _fetch(client, repo)
    for i in range(_FAILING_INDEX):
        assert repo.get_email(f"m{i}") is not None
    assert repo.get_email(f"m{_FAILING_INDEX}") is None


def test_bad_message_is_skipped_not_fatal(repo: Repository) -> None:
    """A single malformed message is skipped; the rest of the batch still processes."""
    sleeps: list[float] = []
    client = _FakeClient(ValueError("malformed"), _FAILING_INDEX)
    result = _fetch(client, repo, sleeps)
    assert result == FetchResult(
        new_emails=_STUB_COUNT - 1, truncated=False,
        processed=_STUB_COUNT, total=_STUB_COUNT,
    )
    assert sleeps == []  # a parse failure is not a quota problem — no waiting
    assert repo.get_email(f"m{_FAILING_INDEX}") is None
    assert repo.get_email(f"m{_STUB_COUNT - 1}") is not None


def test_quota_exhaustion_while_listing_truncates(repo: Repository) -> None:
    """A quota error on the listing call yields an empty truncated result, not a crash."""
    client = _FakeClient(None, _FAILING_INDEX)

    def _boom(query: str, max_results: int = 100) -> list[dict]:
        raise GmailQuotaExhaustedError("quota")

    client.list_messages = _boom
    assert _fetch(client, repo) == FetchResult(
        new_emails=0, truncated=True, processed=0, total=0,
    )


def test_second_sync_fetches_only_the_remainder(repo: Repository) -> None:
    """A later sync picks up where a truncated one stopped, without refetching."""
    first = _fetch(_FakeClient(GmailQuotaExhaustedError("q"), _FAILING_INDEX), repo)
    assert first.truncated and first.new_emails == _FAILING_INDEX

    resumed = _FakeClient(None, _FAILING_INDEX)
    second = _fetch(resumed, repo)
    assert second == FetchResult(
        new_emails=_STUB_COUNT - _FAILING_INDEX, truncated=False,
        processed=_STUB_COUNT, total=_STUB_COUNT,
    )
    # The already-stored prefix costs no API calls.
    assert resumed.fetched == [f"m{i}" for i in range(_FAILING_INDEX, _STUB_COUNT)]
