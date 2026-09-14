"""Tests for GmailClient retry, backoff and request pacing."""

import json
from typing import Any
from unittest.mock import patch

import pytest
from googleapiclient.errors import HttpError
from jobpilot.gmail.client import (
    _JITTER_RATIO,
    _MAX_ATTEMPTS,
    _MAX_BACKOFF_SECONDS,
    _MIN_REQUEST_INTERVAL_SECONDS,
    GmailClient,
    GmailQuotaExhaustedError,
    _is_retryable,
)

# random.uniform is patched to its upper bound so backoff growth is deterministic.
_FIXED_JITTER = _JITTER_RATIO


class _FakeResponse:
    """Minimal httplib2 response stand-in for building HttpError."""

    def __init__(self, status: int):
        self.status = status
        self.reason = "Error"


def _http_error(status: int, reasons: list[str] | None = None) -> HttpError:
    """Build a real HttpError carrying Google's machine-readable error reasons."""
    errors = [{"domain": "usageLimits", "message": "boom", "reason": r} for r in reasons or []]
    payload: dict[str, Any] = {"error": {"code": status, "message": "boom"}}
    if errors:
        payload["error"]["errors"] = errors
    return HttpError(_FakeResponse(status), json.dumps(payload).encode("utf-8"))


class _StubRequest:
    """Request stub whose execute() replays a scripted list of results/exceptions."""

    script_tail: Any = None

    def __init__(self, script: list[Any]):
        self.script = list(script)
        self.attempts = 0

    def execute(self) -> dict:
        self.attempts += 1
        outcome = self.script.pop(0) if self.script else self.script_tail
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _RepeatingRequest(_StubRequest):
    """Request stub that raises the same error on every call."""

    def __init__(self, error: Exception):
        super().__init__([])
        self.script_tail = error


@pytest.fixture
def sleeps() -> list[float]:
    """Collects every sleep duration the client requests."""
    return []


@pytest.fixture
def client(sleeps: list[float]) -> GmailClient:
    """GmailClient with the Google service and jitter stubbed out."""
    with patch("jobpilot.gmail.client.build"):
        return GmailClient(credentials=None, sleep=sleeps.append)


# --- _is_retryable ---

def test_is_retryable_rate_limit_403() -> None:
    """A 403 with reason rateLimitExceeded is retryable."""
    assert _is_retryable(_http_error(403, ["rateLimitExceeded"])) is True


def test_is_retryable_permission_403() -> None:
    """A 403 with reason insufficientPermissions is not retryable."""
    assert _is_retryable(_http_error(403, ["insufficientPermissions"])) is False


def test_is_retryable_404() -> None:
    """A 404 with no error details is not retryable."""
    assert _is_retryable(_http_error(404)) is False


def test_is_retryable_503_regardless_of_details() -> None:
    """A 503 is retryable whatever the error details say."""
    assert _is_retryable(_http_error(503)) is True
    assert _is_retryable(_http_error(503, ["insufficientPermissions"])) is True


# --- _execute retry behaviour ---

def test_execute_retries_then_succeeds(client: GmailClient) -> None:
    """Two 429s then success returns the payload after exactly 3 attempts."""
    request = _StubRequest([_http_error(429), _http_error(429), {"id": "m1"}])
    with patch("jobpilot.gmail.client.random.uniform", return_value=_FIXED_JITTER):
        assert client._execute(request) == {"id": "m1"}
    assert request.attempts == 3


def test_execute_backoff_grows_exponentially(client: GmailClient, sleeps: list[float]) -> None:
    """Backoff sleeps grow between retries and stay within the jittered ceiling."""
    request = _StubRequest([_http_error(429), _http_error(429), {"id": "m1"}])
    with patch("jobpilot.gmail.client.random.uniform", return_value=_FIXED_JITTER):
        client._execute(request)
    # Throttle sleeps are sub-interval; backoff sleeps are the ones >= 1 second.
    backoffs = [s for s in sleeps if s >= _MIN_REQUEST_INTERVAL_SECONDS]
    assert len(backoffs) == 2
    assert backoffs[1] > backoffs[0]
    assert all(s <= _MAX_BACKOFF_SECONDS * (1 + _JITTER_RATIO) for s in backoffs)


def test_get_message_raises_quota_exhausted(client: GmailClient) -> None:
    """A permanently rate-limited request surfaces as GmailQuotaExhaustedError."""
    request = _RepeatingRequest(_http_error(429))
    with patch.object(client, "service"), \
         patch("jobpilot.gmail.client.random.uniform", return_value=_FIXED_JITTER):
        client.service.users.return_value.messages.return_value.get.return_value = request
        with pytest.raises(GmailQuotaExhaustedError):
            client.get_message("m1")
    assert request.attempts == _MAX_ATTEMPTS


def test_execute_does_not_retry_non_retryable(client: GmailClient, sleeps: list[float]) -> None:
    """A 404 raises immediately with no backoff sleep."""
    request = _RepeatingRequest(_http_error(404))
    with pytest.raises(HttpError):
        client._execute(request)
    assert request.attempts == 1
    assert [s for s in sleeps if s >= _MIN_REQUEST_INTERVAL_SECONDS] == []


# --- throttling ---

def test_successive_requests_are_paced(client: GmailClient, sleeps: list[float]) -> None:
    """Back-to-back calls sleep so the two requests are a full interval apart.

    The sleep is the interval minus the time already elapsed, so it is positive but
    never exceeds _MIN_REQUEST_INTERVAL_SECONDS.
    """
    client._execute(_StubRequest([{"id": "a"}]))
    client._execute(_StubRequest([{"id": "b"}]))
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= _MIN_REQUEST_INTERVAL_SECONDS
