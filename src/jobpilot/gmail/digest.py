"""Parse digest emails into individual job listings.

Dispatches by platform to the per-platform parsers. LinkedIn and Indeed parsers
live here; Glassdoor and Wellfound parsers and the shared helpers are imported
from sibling modules and re-exported for backwards-compatible imports.
"""

import re

from jobpilot.gmail.digest_common import (
    _LINKEDIN_JOB_URL,
    MIN_DIGEST_JOBS_FOR_GENERIC,
    _clean_job_url,
    _is_boilerplate_line,
    _parse_generic_digest,
    extract_single_job_url,
)
from jobpilot.gmail.digest_glassdoor import (
    _GLASSDOOR_NOISE_RE,
    _GLASSDOOR_SALARY_RE,
    _parse_glassdoor_digest,
)
from jobpilot.gmail.digest_wellfound import _parse_wellfound_digest
from jobpilot.storage.models import Email, ScrapedJob

__all__ = [
    "parse_digest",
    "extract_single_job_url",
    "_clean_job_url",
    "_is_boilerplate_line",
    "_parse_linkedin_digest",
    "_parse_glassdoor_digest",
    "_parse_wellfound_digest",
    "_GLASSDOOR_NOISE_RE",
    "_GLASSDOOR_SALARY_RE",
]

# LinkedIn-specific patterns
_LINKEDIN_SEPARATOR = re.compile(r"\n\s*-{3,}\s*\n")
_LINKEDIN_VIEW_JOB = re.compile(
    r"(?:View job|Se jobb|Visa jobb):\s*(https?://[^\s]+)", re.IGNORECASE
)

# Lines to skip in LinkedIn blocks
_LINKEDIN_SKIP_LINES = re.compile(
    r"^(This company is actively hiring|Apply with|Promoted|Be an early applicant|"
    r"Reposted|Actively recruiting|\d+ applicant|Easy Apply|Save job|Share|"
    r"New jobs match|Your job alert|Unsubscribe|Help|LinkedIn|See all jobs|"
    r"View job|Se jobb|Visa jobb|More jobs for you)",
    re.IGNORECASE,
)


def parse_digest(email: Email) -> list[ScrapedJob]:
    """Parse a digest email into individual job listings.

    Returns a list of ScrapedJob entries extracted from the email.
    For non-digest emails, returns an empty list (single job URL is handled
    via extract_single_job_url instead).
    """
    body = email.body_text or ""
    if not body.strip():
        return []

    platform = email.platform or ""

    if platform == "linkedin" or "linkedin.com" in (email.sender_domain or ""):
        jobs = _parse_linkedin_digest(body)
    elif platform == "indeed" or "indeed" in (email.sender_domain or ""):
        jobs = _parse_indeed_digest(body)
    elif platform == "glassdoor" or "glassdoor" in (email.sender_domain or ""):
        jobs = _parse_glassdoor_digest(email.body_html or "", body)
    elif platform == "wellfound" or "wellfound" in (email.sender_domain or ""):
        # Wellfound alert emails arrive with an empty platform column, so
        # canonicalize it here — this lets single-job alerts bypass the digest
        # minimum-count gate below and tags the jobs with source "wellfound".
        platform = "wellfound"
        jobs = _parse_wellfound_digest(email.body_html or "", body)
    elif platform == "relocate_me" or "relocate.me" in (email.sender_domain or ""):
        jobs = _parse_generic_digest(body)
    elif platform == "google_alerts" or "google.com" in (email.sender_domain or ""):
        jobs = _parse_generic_digest(body)
    else:
        jobs = _parse_generic_digest(body)

    # Only return if we found multiple jobs (digest), or platform-specific parser found any
    major_platforms = (
        "linkedin", "indeed", "glassdoor", "wellfound", "relocate_me", "google_alerts",
    )
    if len(jobs) < MIN_DIGEST_JOBS_FOR_GENERIC and platform not in major_platforms:
        return []

    return [
        ScrapedJob(
            id=None,
            source=platform or "email",
            title=j["title"],
            company=j.get("company"),
            location=j.get("location"),
            salary=j.get("salary"),
            url=_clean_job_url(j["url"]),
            email_id=email.id,
        )
        for j in jobs
        if j.get("url") and j.get("title") and not _is_boilerplate_line(j["title"])
    ]


def _parse_linkedin_digest(body: str) -> list[dict]:
    """Parse a LinkedIn job alert digest email."""
    jobs = []

    # Try splitting by separator lines first
    blocks = _LINKEDIN_SEPARATOR.split(body)
    if len(blocks) < 2:
        # Try splitting by double newlines if no separator found
        blocks = re.split(r"\n\n\n+", body)

    for block in blocks:
        job = _extract_linkedin_block(block.strip())
        if job:
            jobs.append(job)

    return jobs


def _extract_linkedin_block(block: str) -> dict | None:
    """Extract job info from a single LinkedIn digest block."""
    # Find the URL first — blocks without URLs are headers/footers
    url_match = _LINKEDIN_VIEW_JOB.search(block)
    if not url_match:
        # Try finding a LinkedIn job URL directly
        url_match = _LINKEDIN_JOB_URL.search(block)
        if not url_match:
            return None

    url = url_match.group(0) if not url_match.lastindex else url_match.group(url_match.lastindex)

    # If the match was from _LINKEDIN_JOB_URL, reconstruct full URL
    if _LINKEDIN_JOB_URL.match(url):
        pass  # url is already the full URL
    elif url.startswith("http"):
        pass  # url from View job line
    else:
        return None

    # Extract title, company, location from the lines before the URL
    lines = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        if _LINKEDIN_SKIP_LINES.match(line):
            continue
        if "linkedin.com" in line.lower():
            continue
        if _is_boilerplate_line(line):
            continue
        lines.append(line)

    # Typical order: title, company, location
    title = lines[0] if len(lines) > 0 else None
    company = lines[1] if len(lines) > 1 else None
    location = lines[2] if len(lines) > 2 else None

    if not title:
        return None

    return {"title": title, "company": company, "location": location, "url": url}


def _parse_indeed_digest(body: str) -> list[dict]:
    """Parse an Indeed job alert digest email."""
    # Indeed digests typically have job blocks with URLs
    jobs = []
    # Split by double newlines
    blocks = re.split(r"\n\n\n+", body)

    for block in blocks:
        urls = re.findall(
            r"https?://(?:www\.)?indeed\.com/(?:viewjob|jobs|rc/clk)\b[^\s]*",
            block, re.IGNORECASE,
        )
        if not urls:
            continue

        lines = [line.strip() for line in block.splitlines() if line.strip()]
        # Filter out noise
        content_lines = [
            line for line in lines
            if not line.startswith("http") and "indeed.com" not in line.lower()
            and len(line) > 2 and not _is_boilerplate_line(line)
        ]

        title = content_lines[0] if content_lines else None
        company = content_lines[1] if len(content_lines) > 1 else None
        location = content_lines[2] if len(content_lines) > 2 else None

        if title:
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": urls[0],
            })

    return jobs
