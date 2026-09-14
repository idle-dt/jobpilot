"""Gmail API service wrapper with retry, backoff and request pacing."""

import logging
import random
import time
from collections.abc import Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest

log = logging.getLogger(__name__)

# HTTP statuses Google documents as retryable for the Gmail API.
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
# A 403 is only retryable for these machine-readable reasons; other 403s are permission
# failures that will never succeed on retry.
_RETRYABLE_403_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})

_MAX_ATTEMPTS = 5
_INITIAL_BACKOFF_SECONDS = 1.0
_BACKOFF_MULTIPLIER = 2.0
_MAX_BACKOFF_SECONDS = 64.0
_JITTER_RATIO = 0.25
_MIN_REQUEST_INTERVAL_SECONDS = 0.1

_HTTP_FORBIDDEN = 403
_MAX_PAGE_SIZE = 100


class GmailQuotaExhaustedError(Exception):
    """Raised when a Gmail request is still rate-limited after every retry."""


def _error_reasons(error: HttpError) -> set[str]:
    """Extract Google's machine-readable error reasons from an HttpError."""
    details = error.error_details
    if not isinstance(details, list):
        return set()
    return {d["reason"] for d in details if isinstance(d, dict) and "reason" in d}


def _is_retryable(error: HttpError) -> bool:
    """True when Google indicates the request may succeed if retried."""
    if error.status_code in _RETRYABLE_STATUSES:
        return True
    if error.status_code != _HTTP_FORBIDDEN:
        return False
    return bool(_error_reasons(error) & _RETRYABLE_403_REASONS)


class GmailClient:
    """Thin wrapper around the Gmail API service."""

    def __init__(
        self,
        credentials: Credentials,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.service = build("gmail", "v1", credentials=credentials)
        self._sleep = sleep
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        """Keep at least _MIN_REQUEST_INTERVAL_SECONDS between API calls."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
            self._sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request_at = time.monotonic()

    def _execute(self, request: HttpRequest) -> dict:
        """Execute a Gmail request, retrying retryable errors with backoff."""
        backoff = _INITIAL_BACKOFF_SECONDS
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._throttle()
            try:
                return request.execute()
            except HttpError as error:
                if not _is_retryable(error) or attempt == _MAX_ATTEMPTS:
                    raise
                log.warning(
                    "Gmail API %s (attempt %d/%d), retrying in %.1fs",
                    error.status_code, attempt, _MAX_ATTEMPTS, backoff,
                )
                self._sleep(backoff * (1 + random.uniform(0, _JITTER_RATIO)))
                backoff = min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_SECONDS)
        raise AssertionError("unreachable: loop either returns or raises")

    def _execute_or_quota_error(self, request: HttpRequest) -> dict:
        """Execute a request, translating surviving quota errors for callers."""
        try:
            return self._execute(request)
        except HttpError as error:
            if _is_retryable(error):
                raise GmailQuotaExhaustedError(str(error)) from error
            raise

    def list_messages(self, query: str, max_results: int = 100) -> list[dict]:
        """List message IDs matching a Gmail search query."""
        messages = []
        page_token = None

        while True:
            request = self.service.users().messages().list(
                userId="me",
                q=query,
                pageToken=page_token,
                maxResults=min(max_results - len(messages), _MAX_PAGE_SIZE),
            )
            results = self._execute_or_quota_error(request)

            if "messages" in results:
                messages.extend(results["messages"])

            page_token = results.get("nextPageToken")
            if not page_token or len(messages) >= max_results:
                break

        return messages[:max_results]

    def get_message(self, message_id: str) -> dict:
        """Fetch a full message by ID."""
        request = self.service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        )
        return self._execute_or_quota_error(request)

    def apply_label(self, message_id: str, label_id: str) -> None:
        """Add a label to a message."""
        request = self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        )
        self._execute_or_quota_error(request)

    def get_or_create_label(self, label_name: str) -> str:
        """Get a label ID by name, creating it if it doesn't exist."""
        listing = self._execute_or_quota_error(self.service.users().labels().list(userId="me"))
        for label in listing.get("labels", []):
            if label["name"] == label_name:
                return label["id"]

        create_request = self.service.users().labels().create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        return self._execute_or_quota_error(create_request)["id"]
