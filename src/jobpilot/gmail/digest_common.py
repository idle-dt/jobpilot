"""Shared helpers and constants for digest parsing.

Split out of digest.py so the per-platform parser modules can share the
boilerplate detector, URL cleaner, and generic fallback parser without importing
the dispatcher module (which would create an import cycle).
"""

import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

# URL patterns for known job platforms
JOB_URL_PATTERNS = [
    re.compile(r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/\d+", re.IGNORECASE),
    re.compile(r"https?://(?:www\.)?indeed\.com/(?:viewjob|jobs)\b[^\s]*", re.IGNORECASE),
    re.compile(r"https?://(?:www\.)?glassdoor\.com/job-listing/[^\s]*", re.IGNORECASE),
    re.compile(r"https?://(?:www\.)?glassdoor\.com/partner/jobListing\.htm[^\s]*", re.IGNORECASE),
    re.compile(r"https?://(?:www\.)?relocate\.me/[^\s]*", re.IGNORECASE),
    re.compile(r"https?://(?:www\.)?wellfound\.com/jobs/[^\s]*", re.IGNORECASE),
    re.compile(r"https?://links\.wellfound\.com/s/c/[^\s]*", re.IGNORECASE),
    re.compile(r"https?://(?:www\.)?arc\.dev/[^\s]*jobs?[^\s]*", re.IGNORECASE),
]

# Generic URL pattern — any http(s) URL
_ANY_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

# LinkedIn job-view URL — shared by the URL cleaner and the LinkedIn parser.
_LINKEDIN_JOB_URL = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)", re.IGNORECASE
)

# Glassdoor generates a unique tracking URL per digest for the same job (the
# pos/guid/cb params differ; only jobListingId is stable). Normalizing to just
# jobListingId lets the UNIQUE constraint collapse duplicates across digests.
_GLASSDOOR_LISTING_MARKER = "partner/jobListing"
_GLASSDOOR_LISTING_PARAM = "jobListingId"
_GLASSDOOR_LISTING_URL = (
    "https://www.glassdoor.com/partner/jobListing.htm?jobListingId={job_id}"
)

# Known boilerplate phrases that appear in LinkedIn "alert created" emails
_BOILERPLATE_PATTERNS = re.compile(
    r"(you'll receive notifications|match(es)? your (search )?preferences|"
    r"job alert has been created|new jobs? (are |is )?posted|"
    r"a new job matches|new job match|"
    r"based on your profile|jobs for you)",
    re.IGNORECASE,
)

# CTA / button text that digest parsers can mistake for a job title.
# All entries are lowercase — compared via stripped.lower().
_CTA_PHRASES = frozenset({
    "learn more", "apply now", "apply", "view job", "view jobs",
    "view all jobs", "see job", "see all jobs", "see more",
    "read more", "click here", "sign in", "sign up", "subscribe",
    "unsubscribe", "manage alerts", "view details", "more info",
    "get started", "create alert", "update preferences",
})

# Words that indicate a line is a sentence, not a job title
_SENTENCE_WORDS = re.compile(r"\b(you|your|when|that|will|we'll|you'll)\b", re.IGNORECASE)

# Abbreviations that legitimately end job titles with a period (e.g. "Sr.", "Jr.")
_TITLE_ABBREV_RE = re.compile(r"\b(Sr|Jr|Inc|Ltd|Corp|Co|Dr|Mr|Mrs|Ms)\.$", re.IGNORECASE)

# Known lowercase-start tech prefixes that are valid title starts, not sentences
_LOWERCASE_TITLE_PREFIXES = ("iOS", "iPad", "iPhone", "eBay", "eCommerce", "eLearning")

# Digest parsing thresholds
MAX_BOILERPLATE_LINE_LENGTH = 120
MIN_SENTENCE_LINE_LENGTH = 40
MIN_DIGEST_JOBS_FOR_GENERIC = 2
GENERIC_URL_CONTEXT_LINES = 5


def _is_boilerplate_line(line: str) -> bool:
    """Check if a line is boilerplate intro text rather than a job title."""
    stripped = line.strip()
    if stripped.lower() in _CTA_PHRASES:
        return True
    if _BOILERPLATE_PATTERNS.search(stripped):
        return True
    if len(stripped) > MAX_BOILERPLATE_LINE_LENGTH:
        return True
    if len(stripped) > MIN_SENTENCE_LINE_LENGTH and _SENTENCE_WORDS.search(stripped):
        return True
    # Sentence fragments: starts lowercase + contains sentence words or is long
    # (allows "iOS Developer", "eBay Engineer" etc.)
    if stripped and stripped[0].islower() and (
        _SENTENCE_WORDS.search(stripped) or len(stripped) > MIN_SENTENCE_LINE_LENGTH
    ):
        if not any(stripped.startswith(prefix) for prefix in _LOWERCASE_TITLE_PREFIXES):
            return True
    # Ends with period but not a known abbreviation (e.g. "Sr.", "...Inc.")
    if stripped.endswith(".") and not _TITLE_ABBREV_RE.search(stripped):
        return True
    return False


def _find_job_urls(text: str) -> list[str]:
    """Find all job platform URLs in text."""
    urls = []
    for pattern in JOB_URL_PATTERNS:
        urls.extend(pattern.findall(text))
    return urls


def _clean_job_url(url: str) -> str:
    """Strip tracking parameters from a job URL, keeping the essential parts."""
    parsed = urlparse(url)

    # LinkedIn: keep just /jobs/view/ID
    match = _LINKEDIN_JOB_URL.search(url)
    if match:
        job_id = match.group(1)
        return f"https://www.linkedin.com/jobs/view/{job_id}/"

    # Glassdoor: keep only jobListingId so the same job across digests dedups
    if _GLASSDOOR_LISTING_MARKER in parsed.path or _GLASSDOOR_LISTING_MARKER in url:
        if parsed.query:
            job_id = parse_qs(parsed.query).get(_GLASSDOOR_LISTING_PARAM, [None])[0]
            if job_id:
                return _GLASSDOOR_LISTING_URL.format(job_id=job_id)

    # For other URLs, strip common tracking params
    tracking_params = {
        "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
        "refId", "trackingId", "trk", "midToken", "midSig", "trkEmail",
        "eBP", "rcposting", "ts", "ref", "tk", "jbr", "from",
    }
    if parsed.query:
        params = parse_qs(parsed.query)
        cleaned = {k: v for k, v in params.items() if k not in tracking_params}
        cleaned_query = urlencode(cleaned, doseq=True) if cleaned else ""
        return urlunparse(parsed._replace(query=cleaned_query, fragment=""))

    return urlunparse(parsed._replace(fragment=""))


def extract_single_job_url(body: str, platform: str | None = None) -> str | None:
    """Extract a single job URL from a non-digest email body.

    Returns the cleaned URL if exactly one job URL is found, else None.
    """
    if not body:
        return None

    urls = _find_job_urls(body)
    # Deduplicate by cleaned URL
    seen = set()
    unique = []
    for u in urls:
        cleaned = _clean_job_url(u)
        if cleaned not in seen:
            seen.add(cleaned)
            unique.append(cleaned)

    if len(unique) == 1:
        return unique[0]

    # If multiple URLs but all point to the same job, return it
    if len(unique) > 1:
        # Check if they're all the same after cleaning
        return None

    return None


def _parse_generic_digest(body: str) -> list[dict]:
    """Generic fallback parser — finds all job URLs and extracts nearby context."""
    all_urls = _ANY_URL_RE.findall(body)

    # Filter to job-related URLs only
    job_urls = []
    for url in all_urls:
        for pattern in JOB_URL_PATTERNS:
            if pattern.match(url):
                job_urls.append(url)
                break

    if not job_urls:
        return []

    jobs = []
    lines = body.splitlines()

    for url in job_urls:
        # Find which line contains this URL
        url_line_idx = None
        for i, line in enumerate(lines):
            if url in line:
                url_line_idx = i
                break

        if url_line_idx is None:
            jobs.append({"title": url, "url": url})
            continue

        # Look at lines before the URL for title/company/location
        context_lines = []
        for i in range(max(0, url_line_idx - GENERIC_URL_CONTEXT_LINES), url_line_idx):
            line = lines[i].strip()
            if (line and len(line) > 2
                    and not line.startswith("http")
                    and not _is_boilerplate_line(line)):
                context_lines.append(line)

        title = context_lines[-1] if context_lines else None
        company = context_lines[-2] if len(context_lines) > 1 else None
        location = context_lines[-3] if len(context_lines) > 2 else None

        if title:
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": url,
            })
        else:
            jobs.append({"title": url, "url": url})

    return jobs
