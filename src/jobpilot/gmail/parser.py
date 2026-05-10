"""Email body parsing and signal extraction."""

import base64
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from jobpilot.classifier.signals import detect_platform, extract_signals
from jobpilot.storage.models import Email, ExtractedSignal


def parse_message(raw: dict) -> Email:
    """Parse a raw Gmail API message into an Email model with extracted signals."""
    msg_id = raw["id"]
    thread_id = raw["threadId"]
    headers = {h["name"].lower(): h["value"] for h in raw["payload"]["headers"]}

    sender = headers.get("from", "")
    subject = headers.get("subject", "")
    date_str = headers.get("date", "")

    sender_domain = _extract_domain(sender)
    received_at = _parse_date(date_str)

    body_html, body_text = _extract_body(raw["payload"])

    # If we only got HTML, convert to text
    if body_html and not body_text:
        body_text = _html_to_text(body_html)

    platform = detect_platform(sender, sender_domain, subject)
    signals = extract_signals(subject, body_text or "", platform)

    email = Email(
        id=msg_id,
        thread_id=thread_id,
        sender=sender,
        sender_domain=sender_domain,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        received_at=received_at,
        platform=platform,
    )
    # Attach signals for the fetcher to store separately
    email._signals = [
        ExtractedSignal(id=None, email_id=msg_id, signal_type=s["type"], signal_value=s["value"])
        for s in signals
    ]
    return email


def _extract_domain(sender: str) -> str:
    """Extract domain from a 'Name <email@domain.com>' string."""
    match = re.search(r"@([\w.-]+)", sender)
    return match.group(1).lower() if match else ""


def _parse_date(date_str: str) -> datetime:
    """Parse an email Date header into a datetime."""
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(timezone.utc)


def _extract_body(payload: dict) -> tuple[str | None, str | None]:
    """Recursively extract HTML and plain text body from message payload."""
    html = None
    text = None

    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if body_data:
        decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
        if "html" in mime_type:
            html = decoded
        elif "plain" in mime_type:
            text = decoded

    for part in payload.get("parts", []):
        part_html, part_text = _extract_body(part)
        if part_html:
            html = part_html
        if part_text:
            text = part_text

    return html, text


def _html_to_text(html: str) -> str:
    """Convert HTML to readable plain text."""
    soup = BeautifulSoup(html, "lxml")

    # Remove script and style elements
    for element in soup(["script", "style", "head"]):
        element.decompose()

    text = soup.get_text(separator="\n")

    # Collapse whitespace
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)
