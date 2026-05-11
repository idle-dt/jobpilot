"""Tests for email parsing and signal extraction."""

import base64

from jobpilot.classifier.signals import detect_platform, extract_signals
from jobpilot.gmail.parser import _extract_body, _extract_domain, _html_to_text, parse_message


# --- Helper to build fake Gmail API messages ---

def _make_raw_message(
    msg_id: str = "msg_test",
    thread_id: str = "thread_test",
    sender: str = "jobs@linkedin.com",
    subject: str = "New job: Senior Flutter Developer",
    body_text: str = "Great Flutter role in Amsterdam",
    body_html: str | None = None,
    date: str = "Mon, 15 Jan 2024 10:30:00 +0000",
) -> dict:
    parts = []
    if body_text:
        parts.append({
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(body_text.encode()).decode()},
        })
    if body_html:
        parts.append({
            "mimeType": "text/html",
            "body": {"data": base64.urlsafe_b64encode(body_html.encode()).decode()},
        })

    payload = {
        "mimeType": "multipart/alternative" if len(parts) > 1 else parts[0]["mimeType"],
        "headers": [
            {"name": "From", "value": sender},
            {"name": "Subject", "value": subject},
            {"name": "Date", "value": date},
        ],
        "parts": parts if len(parts) > 1 else [],
    }

    # Single-part: put body directly on payload
    if len(parts) == 1:
        payload["body"] = parts[0]["body"]

    return {"id": msg_id, "threadId": thread_id, "payload": payload}


# --- Domain Extraction ---

def test_extract_domain_angle_brackets():
    assert _extract_domain("LinkedIn <jobs@linkedin.com>") == "linkedin.com"


def test_extract_domain_plain():
    assert _extract_domain("jobs@wellfound.com") == "wellfound.com"


def test_extract_domain_empty():
    assert _extract_domain("no email here") == ""


# --- Platform Detection ---

def test_detect_linkedin():
    assert detect_platform("jobs@linkedin.com", "linkedin.com", "New jobs for you") == "linkedin"


def test_detect_wellfound():
    assert detect_platform("team@wellfound.com", "wellfound.com", "New match") == "wellfound"


def test_detect_relocate_me():
    assert detect_platform("hi@relocate.me", "relocate.me", "Jobs") == "relocate_me"


def test_detect_unknown():
    assert detect_platform("random@example.com", "example.com", "Hello") is None


def test_detect_indeed():
    assert detect_platform("alert@indeed.com", "indeed.com", "New jobs") == "indeed"


def test_detect_google_alerts():
    assert detect_platform(
        "googlealerts-noreply@google.com", "google.com", "Google Alert"
    ) == "google_alerts"


# --- Signal Extraction ---

def test_extract_tech_signals():
    signals = extract_signals("Flutter Developer", "We use dart and kotlin", "linkedin")
    tech_values = [s["value"] for s in signals if s["type"] == "tech_stack"]
    assert "flutter" in tech_values
    assert "dart" in tech_values
    assert "kotlin" in tech_values


def test_extract_location_signals():
    signals = extract_signals("Job in Amsterdam", "Netherlands office, remote option", None)
    locations = [s["value"] for s in signals if s["type"] == "location"]
    assert "netherlands" in locations
    assert "remote" in locations


def test_extract_seniority():
    signals = extract_signals("Senior Flutter Developer", "Looking for a senior dev", None)
    seniority = [s for s in signals if s["type"] == "seniority"]
    assert len(seniority) == 1
    assert seniority[0]["value"] == "senior"


def test_extract_negative_signals():
    signals = extract_signals("Job", "No visa sponsorship. Security clearance required.", None)
    negatives = [s["value"] for s in signals if s["type"] == "negative"]
    assert "no visa sponsorship" in negatives
    assert "security clearance" in negatives


def test_extract_salary_eur():
    signals = extract_signals("Job", "Salary range: €60,000 - €90,000", None)
    salary = [s for s in signals if s["type"] == "salary"]
    assert len(salary) == 1


def test_extract_salary_k_notation():
    signals = extract_signals("Job", "Offering 80k-120k EUR", None)
    salary = [s for s in signals if s["type"] == "salary"]
    assert len(salary) == 1


# --- Full Message Parsing ---

def test_parse_plain_text_message():
    raw = _make_raw_message(
        sender="LinkedIn <jobs-noreply@linkedin.com>",
        subject="Senior Flutter Developer at TechCorp - Amsterdam",
        body_text="Senior Flutter position in Amsterdam, Netherlands. "
                  "Tech stack: Flutter, Dart, Kotlin. Salary: €80,000 - €110,000.",
    )
    email, signals = parse_message(raw)

    assert email.id == "msg_test"
    assert email.sender_domain == "linkedin.com"
    assert email.platform == "linkedin"
    assert "Flutter" in email.subject
    assert email.body_text is not None
    assert len(signals) > 0

    signal_types = {s.signal_type for s in signals}
    assert "tech_stack" in signal_types
    assert "location" in signal_types
    assert "platform" in signal_types


def test_parse_html_only_message():
    raw = _make_raw_message(
        body_text=None,
        body_html="<html><body><h1>Flutter Developer</h1><p>Great role in Oslo</p></body></html>",
    )
    email, signals = parse_message(raw)

    assert email.body_text is not None
    assert "Flutter Developer" in email.body_text
    assert "Oslo" in email.body_text


def test_html_to_text_strips_scripts():
    html = "<html><script>alert('x')</script><body><p>Hello</p></body></html>"
    text = _html_to_text(html)
    assert "alert" not in text
    assert "Hello" in text
