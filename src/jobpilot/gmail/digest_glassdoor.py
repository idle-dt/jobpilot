"""Glassdoor job-alert digest parser."""

import re

from bs4 import BeautifulSoup
from bs4.element import Tag

from jobpilot.gmail.digest_common import _parse_generic_digest

# Glassdoor parsing thresholds
GLASSDOOR_MAX_PARENT_DEPTH = 12
GLASSDOOR_MIN_CONTEXT_LENGTH = 30
GLASSDOOR_MAX_CONTEXT_LENGTH = 500
GLASSDOOR_MIN_TEXT_LENGTH = 10
GLASSDOOR_MIN_CONTENT_PARTS = 3


_GLASSDOOR_RATING_RE = re.compile(r"^(\d+\.\d+\s*★?|★)$")
# Matches a standalone salary range like "$150K - $220K" or "$85K - $103K".
# Anchored at both ends so titles containing parenthetical amounts (e.g.
# "Sr Engineer ($150-$220k) AI") are NOT mistaken for a salary value.
_GLASSDOOR_SALARY_RE = re.compile(r"^\$[\d,.]+[KkMm]?\s*[-–]\s*\$[\d,.]+[KkMm]?$")
_GLASSDOOR_NOISE_RE = re.compile(
    # \d+[dh]$ is end-anchored so only standalone age tokens ("22h", "3d") match,
    # not real content that merely starts with them ("3D Artist", "24h support").
    r"^(Glassdoor est\.|Employer est\.|Easy Apply|\d+[dh]$|See more jobs|"
    r"Want more listings|Similar jobs|Create|Looking for|You can edit|"
    r"Sent Daily|Edit|This message was sent|Privacy Policy|Manage Settings|"
    r"Unsubscribe|Glassdoor|Copyright|\(|\)|operations analyst|systems analyst|"
    r"engineering documentation|Highly Rated)",
    re.IGNORECASE,
)


def _parse_glassdoor_digest(html: str, body_text: str) -> list[dict]:
    """Parse a Glassdoor job alert digest from HTML.

    Glassdoor emails have job URLs only in HTML (as /partner/jobListing.htm links),
    with job title, company, location, and salary in the surrounding table cells.
    """
    if not html:
        return _parse_generic_digest(body_text)

    soup = BeautifulSoup(html, "lxml")
    jobs = []
    # A single digest lists the same posting multiple times with different
    # jobListingId links, so dedup within the email by (title, company, location).
    seen: set[tuple[str, str | None, str | None]] = set()

    for link in soup.find_all("a", href=True):
        job = _glassdoor_job_from_link(link, seen)
        if job:
            jobs.append(job)

    return jobs


def _glassdoor_job_from_link(
    link: Tag, seen: set[tuple[str, str | None, str | None]],
) -> dict | None:
    """Extract a deduped job dict from one Glassdoor listing link, or None."""
    href = link["href"]
    if "partner/jobListing" not in href:
        return None

    text = _glassdoor_card_text(link)
    if len(text) < GLASSDOOR_MIN_TEXT_LENGTH:
        return None

    parts = [p.strip() for p in text.split("|") if p.strip()]
    title, company, location, salary = _parse_glassdoor_parts(parts)
    if not title:
        return None

    key = (title, company, location)
    if key in seen:
        return None
    seen.add(key)

    return {
        "title": title,
        "company": company,
        "location": location,
        "salary": salary,
        "url": href,
    }


def _glassdoor_card_text(link: Tag) -> str:
    """Walk up from a job link to its containing card element and return the text."""
    parent = link
    text = ""
    for _ in range(GLASSDOOR_MAX_PARENT_DEPTH):
        parent = parent.parent
        if parent is None:
            break
        text = parent.get_text(separator="|", strip=True)
        if GLASSDOOR_MIN_CONTEXT_LENGTH < len(text) < GLASSDOOR_MAX_CONTEXT_LENGTH:
            break
    return text


def _parse_glassdoor_parts(
    parts: list[str],
) -> tuple[str | None, str | None, str | None, str | None]:
    """Split card text parts into (title, company, location, salary).

    Typical pattern after filtering rating/noise/salary tokens: company, title,
    location. Shorter cards collapse to title [+ location].
    """
    title = company = location = salary = None
    content_parts = []
    for part in parts:
        if _GLASSDOOR_RATING_RE.match(part) or _GLASSDOOR_NOISE_RE.match(part):
            continue
        if _GLASSDOOR_SALARY_RE.match(part):
            salary = part
            continue
        content_parts.append(part)

    if len(content_parts) >= GLASSDOOR_MIN_CONTENT_PARTS:
        company, title, location = content_parts[0], content_parts[1], content_parts[2]
    elif len(content_parts) == 2:
        title, location = content_parts[0], content_parts[1]
    elif len(content_parts) == 1:
        title = content_parts[0]
    return title, company, location, salary
