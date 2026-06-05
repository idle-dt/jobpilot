"""Parse digest emails into individual job listings."""

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from jobpilot.storage.models import Email, ScrapedJob

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

# LinkedIn-specific patterns
_LINKEDIN_SEPARATOR = re.compile(r"\n\s*-{3,}\s*\n")
_LINKEDIN_VIEW_JOB = re.compile(
    r"(?:View job|Se jobb|Visa jobb):\s*(https?://[^\s]+)", re.IGNORECASE
)
_LINKEDIN_JOB_URL = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)", re.IGNORECASE
)

# Lines to skip in LinkedIn blocks
_LINKEDIN_SKIP_LINES = re.compile(
    r"^(This company is actively hiring|Apply with|Promoted|Be an early applicant|"
    r"Reposted|Actively recruiting|\d+ applicant|Easy Apply|Save job|Share|"
    r"New jobs match|Your job alert|Unsubscribe|Help|LinkedIn|See all jobs|"
    r"View job|Se jobb|Visa jobb|More jobs for you)",
    re.IGNORECASE,
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
GLASSDOOR_MAX_PARENT_DEPTH = 12
GLASSDOOR_MIN_CONTEXT_LENGTH = 30
GLASSDOOR_MAX_CONTEXT_LENGTH = 500
GLASSDOOR_MIN_TEXT_LENGTH = 10
GLASSDOOR_MIN_CONTENT_PARTS = 3
GENERIC_URL_CONTEXT_LINES = 5

# Wellfound HTML digest structure. A job card's title is a bold 14px black div.
# The greeting banner (24px, with a background-color) and the "Our take" blurb
# (12px, colored accent) also use font-weight:700, so all three style fragments
# are required to single out a real job title. The company sits in a colored
# span inside the same table cell.
_WELLFOUND_TITLE_STYLE_PARTS = ("font-size: 14px", "font-weight: 700", "color: #000")
_WELLFOUND_COMPANY_COLOR = "#541142"
_WELLFOUND_URL_HOST = "wellfound.com"
# The "Learn more" CTA is a links.wellfound.com redirect pointing at the specific
# job; a card also carries a wellfound.com/company/<slug>/jobs link to the
# company page. Prefer the former and never store the company page.
_WELLFOUND_REDIRECT_HOST = "links.wellfound.com"
_WELLFOUND_COMPANY_PATH = "/company/"
_SAFE_URL_SCHEMES = ("http://", "https://")


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


_GLASSDOOR_RATING_RE = re.compile(r"^(\d+\.\d+\s*★?|★)$")
_GLASSDOOR_NOISE_RE = re.compile(
    r"^(Glassdoor est\.|Employer est\.|Easy Apply|\d+d|See more jobs|"
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

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "partner/jobListing" not in href:
            continue

        # Walk up to find the containing card element with job context
        parent = link
        text = ""
        for _ in range(GLASSDOOR_MAX_PARENT_DEPTH):
            parent = parent.parent
            if parent is None:
                break
            text = parent.get_text(separator="|", strip=True)
            if GLASSDOOR_MIN_CONTEXT_LENGTH < len(text) < GLASSDOOR_MAX_CONTEXT_LENGTH:
                break

        if len(text) < GLASSDOOR_MIN_TEXT_LENGTH:
            continue

        parts = [p.strip() for p in text.split("|") if p.strip()]

        # Extract structured fields from the parts
        # Typical pattern: company [, rating], title, location [, salary, ...]
        title = None
        company = None
        location = None
        salary = None

        content_parts = []
        for part in parts:
            if _GLASSDOOR_RATING_RE.match(part):
                continue
            if _GLASSDOOR_NOISE_RE.match(part):
                continue
            if part.startswith("$") or ("$" in part and "K" in part.upper()):
                salary = part
                continue
            content_parts.append(part)

        # After filtering: typically [company, title, location]
        if len(content_parts) >= GLASSDOOR_MIN_CONTENT_PARTS:
            company = content_parts[0]
            title = content_parts[1]
            location = content_parts[2]
        elif len(content_parts) == 2:
            title = content_parts[0]
            location = content_parts[1]
        elif len(content_parts) == 1:
            title = content_parts[0]

        if not title:
            continue

        jobs.append({
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "url": href,
        })

    return jobs


def _is_wellfound_title_style(style: str | None) -> bool:
    """Return True if a div's style matches Wellfound's job-title signature."""
    return bool(style) and all(part in style for part in _WELLFOUND_TITLE_STYLE_PARTS)


def _parse_wellfound_digest(html: str, body_text: str) -> list[dict]:
    """Parse a Wellfound job alert digest from HTML.

    Wellfound emails are deeply nested tables; the plain-text body smushes every
    field together, so the generic text parser produces garbage. Each job card is
    a table cell holding a bold title div and a colored company span, with a
    links.wellfound.com redirect in the enclosing table. The primary job is
    rendered twice, so jobs are deduped by (title, company). Falls back to the
    generic text parser when no HTML is available.
    """
    if not html:
        return _parse_generic_digest(body_text)

    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []
    seen: set[tuple[str, str | None]] = set()

    for title_div in soup.find_all("div", style=_is_wellfound_title_style):
        title = title_div.get_text(strip=True)
        cell = title_div.find_parent("td")
        if not title or cell is None:
            continue
        company = _wellfound_company(cell)
        if (title, company) in seen:
            continue
        url = _wellfound_job_url(cell.find_parent("table"))
        if url is None:
            continue
        seen.add((title, company))
        jobs.append({"title": title, "company": company, "url": url})

    return jobs


def _wellfound_company(cell: Tag) -> str | None:
    """Extract the company name from a Wellfound job card's table cell."""
    span = cell.find("span", style=lambda s: s and _WELLFOUND_COMPANY_COLOR in s)
    return span.get_text(strip=True) if span else None


def _wellfound_job_url(container: Tag | None) -> str | None:
    """Return the best Wellfound job link in a container, or None.

    Prefers the "Learn more" tracking redirect (links.wellfound.com), which
    targets the specific job, over a wellfound.com/company/<slug> page. The href
    comes from untrusted email HTML, so reject non-HTTP schemes (e.g.
    ``javascript:``) and links that don't point at Wellfound.
    """
    if container is None:
        return None
    fallback: str | None = None
    for anchor in container.find_all("a", href=True):
        href = anchor["href"]
        if not href.startswith(_SAFE_URL_SCHEMES):
            continue
        parsed = urlparse(href)
        host = parsed.hostname or ""
        if host == _WELLFOUND_REDIRECT_HOST:
            return href
        is_wellfound = host == _WELLFOUND_URL_HOST or host.endswith(f".{_WELLFOUND_URL_HOST}")
        if is_wellfound and _WELLFOUND_COMPANY_PATH not in parsed.path and fallback is None:
            fallback = href
    return fallback


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
