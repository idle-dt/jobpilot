"""Tests for digest email parsing."""

from datetime import datetime, timezone

from jobpilot.gmail.digest import (
    _clean_job_url,
    _is_boilerplate_line,
    _parse_glassdoor_digest,
    _parse_linkedin_digest,
    extract_single_job_url,
    parse_digest,
)
from jobpilot.storage.models import Email


def _make_email(
    body_text: str,
    platform: str | None = "linkedin",
    sender_domain: str = "linkedin.com",
    email_id: str = "test_email_1",
) -> Email:
    return Email(
        id=email_id,
        thread_id="thread_1",
        sender=f"jobs@{sender_domain}",
        sender_domain=sender_domain,
        subject="Your job alert",
        received_at=datetime.now(timezone.utc),
        body_text=body_text,
        platform=platform,
    )


LINKEDIN_DIGEST = """\
Your job alert for senior mobile engineer in Sweden
New jobs match your preferences.

Senior App-utvecklare
Deploja
Gothenburg
View job: https://www.linkedin.com/comm/jobs/view/4408668238/?midToken=abc123&trk=eml

---------------------------------------------------------

Android Developer
E-Solutions
Stockholm
View job: https://www.linkedin.com/comm/jobs/view/4407811915/?midToken=xyz456

---------------------------------------------------------

Senior iOS Developer
Incluso
Stockholm
View job: https://www.linkedin.com/comm/jobs/view/4410029616/?midToken=def789
"""


def test_parse_linkedin_digest_extracts_three_jobs():
    email = _make_email(LINKEDIN_DIGEST)
    jobs = parse_digest(email)
    assert len(jobs) == 3


def test_parse_linkedin_digest_titles():
    email = _make_email(LINKEDIN_DIGEST)
    jobs = parse_digest(email)
    titles = [j.title for j in jobs]
    assert "Senior App-utvecklare" in titles
    assert "Android Developer" in titles
    assert "Senior iOS Developer" in titles


def test_parse_linkedin_digest_companies():
    email = _make_email(LINKEDIN_DIGEST)
    jobs = parse_digest(email)
    companies = [j.company for j in jobs]
    assert "Deploja" in companies
    assert "E-Solutions" in companies
    assert "Incluso" in companies


def test_parse_linkedin_digest_locations():
    email = _make_email(LINKEDIN_DIGEST)
    jobs = parse_digest(email)
    locations = [j.location for j in jobs]
    assert "Gothenburg" in locations
    assert "Stockholm" in locations


def test_parse_linkedin_digest_urls_cleaned():
    email = _make_email(LINKEDIN_DIGEST)
    jobs = parse_digest(email)
    urls = [j.url for j in jobs]
    # Tracking params should be stripped
    assert "https://www.linkedin.com/jobs/view/4408668238/" in urls
    assert "https://www.linkedin.com/jobs/view/4407811915/" in urls
    assert "https://www.linkedin.com/jobs/view/4410029616/" in urls
    # No tracking params
    for url in urls:
        assert "midToken" not in url
        assert "trk" not in url


def test_parse_linkedin_digest_email_id():
    email = _make_email(LINKEDIN_DIGEST, email_id="email_abc")
    jobs = parse_digest(email)
    for job in jobs:
        assert job.email_id == "email_abc"
        assert job.source == "linkedin"


def test_parse_linkedin_digest_source():
    email = _make_email(LINKEDIN_DIGEST)
    jobs = parse_digest(email)
    for job in jobs:
        assert job.source == "linkedin"


def test_non_digest_email_returns_empty():
    body = "Someone viewed your profile on LinkedIn."
    email = _make_email(body)
    jobs = parse_digest(email)
    assert jobs == []


def test_empty_body_returns_empty():
    email = _make_email("")
    jobs = parse_digest(email)
    assert jobs == []


def test_single_job_email_not_treated_as_digest():
    body = """\
New job match for you

Senior Flutter Developer
TechCorp
Amsterdam
View job: https://www.linkedin.com/comm/jobs/view/1234567890/
"""
    email = _make_email(body)
    # LinkedIn parser returns even single jobs since it's a known platform
    jobs = parse_digest(email)
    assert len(jobs) == 1


# --- URL Cleaning ---

def test_clean_linkedin_url():
    url = "https://www.linkedin.com/comm/jobs/view/4408668238/?midToken=abc&trk=eml"
    assert _clean_job_url(url) == "https://www.linkedin.com/jobs/view/4408668238/"


def test_clean_url_strips_utm():
    url = "https://example.com/jobs/123?utm_source=email&utm_medium=digest&id=456"
    cleaned = _clean_job_url(url)
    assert "utm_source" not in cleaned
    assert "id=456" in cleaned


def test_clean_url_no_params():
    url = "https://www.linkedin.com/jobs/view/123456/"
    assert _clean_job_url(url) == "https://www.linkedin.com/jobs/view/123456/"


# --- Single Job URL Extraction ---

def test_extract_single_job_url():
    body = "Check out this role: https://www.linkedin.com/jobs/view/9999999/"
    url = extract_single_job_url(body, "linkedin")
    assert url == "https://www.linkedin.com/jobs/view/9999999/"


def test_extract_single_job_url_none_for_multiple():
    body = """\
https://www.linkedin.com/jobs/view/111/
https://www.linkedin.com/jobs/view/222/
"""
    url = extract_single_job_url(body, "linkedin")
    assert url is None


# --- Boilerplate Filtering ---

LINKEDIN_ALERT_CREATED = """\
Your job alert has been created: Senior Software Engineer in United States

You'll receive notifications when new jobs are posted that match your search preferences.

Senior Software Engineer (Remote)
Quik Hire Staffing
United States
View job: https://www.linkedin.com/comm/jobs/view/1111111111/

---------------------------------------------------------

Senior Software Developer (Remote)
Quik Hire Staffing
United States
View job: https://www.linkedin.com/comm/jobs/view/2222222222/
"""


def test_linkedin_alert_created_filters_boilerplate():
    """Boilerplate intro line should not be extracted as a job title."""
    email = _make_email(LINKEDIN_ALERT_CREATED)
    jobs = parse_digest(email)
    titles = [j.title for j in jobs]
    # The boilerplate line must NOT appear as a title
    for title in titles:
        assert "you'll receive notifications" not in title.lower()
        assert "match your search preferences" not in title.lower()
    # Real job titles should still be extracted
    assert "Senior Software Engineer (Remote)" in titles
    assert "Senior Software Developer (Remote)" in titles


def test_long_sentence_filtered_as_boilerplate():
    """Lines longer than 80 characters should be filtered out as boilerplate."""
    body = """\
This is a very long sentence that definitely should not be treated as a job title because it is way too long for any real position

Senior Flutter Developer
TechCorp
Amsterdam
View job: https://www.linkedin.com/comm/jobs/view/3333333333/
"""
    blocks = _parse_linkedin_digest(body)
    for block in blocks:
        assert len(block["title"]) <= 80


def test_extract_single_job_url_none_for_no_urls():
    body = "No job links here, just plain text."
    url = extract_single_job_url(body, "linkedin")
    assert url is None


# --- Boilerplate detection: lowercase tech prefixes ---

def test_lowercase_tech_prefix_titles_not_boilerplate():
    """Titles starting with iOS/iPad/eBay etc. must not be filtered."""
    assert not _is_boilerplate_line(
        "iOS Developer - Native Mobile Platforms (Kotlin Multiplatform)"
    )
    assert not _is_boilerplate_line("iPad App Engineer - Consumer Products")
    assert not _is_boilerplate_line("eBay Senior Backend Engineer")


def test_long_title_with_parentheticals_not_boilerplate():
    """An 82-char title with tech stack and gender marker must not be filtered."""
    title = (
        "Lead Developer Mobile Apps (iOS, Android, Web) / "
        "Digital Health Excellence Center (w/m/d)"
    )
    assert not _is_boilerplate_line(title)


def test_cta_sentence_still_filtered():
    """Real boilerplate CTA lines must still be filtered."""
    assert _is_boilerplate_line(
        "you'll receive notifications when new jobs are posted"
    )


def test_very_long_sentence_still_filtered():
    """A line longer than the 120-char limit must still be filtered."""
    long_line = (
        "Principal Distinguished Staff Architect Engineer Lead Manager Director "
        "of Platform Infrastructure and Reliability Systems Group Worldwide"
    )
    assert len(long_line) > 120
    assert _is_boilerplate_line(long_line)


def test_linkedin_ios_title_parsed_correctly():
    """LinkedIn block with an iOS title parses title/company/location correctly."""
    body = (
        "iOS Developer - Native Mobile Platforms (KMP)\n"
        "iO\n"
        "Amsterdam\n"
        "View job: https://www.linkedin.com/comm/jobs/view/123456789/\n"
    )
    blocks = _parse_linkedin_digest(body)
    assert len(blocks) == 1
    assert blocks[0]["title"] == "iOS Developer - Native Mobile Platforms (KMP)"
    assert blocks[0]["company"] == "iO"
    assert blocks[0]["location"] == "Amsterdam"


# --- Glassdoor: rating and star on separate lines ---

GLASSDOOR_SEPARATE_RATING_HTML = """\
<html><body>
<table><tr><td>
  <div>Visa Inc.</div>
  <div>3.9</div>
  <div>★</div>
  <a href="https://www.glassdoor.com/partner/jobListing.htm?pos=101&jl=123">Software Engineer</a>
  <div>Stockholm</div>
</td></tr></table>
</body></html>
"""


def test_glassdoor_separate_rating_and_star_filtered():
    """Standalone rating and star lines are filtered; fields extracted correctly."""
    jobs = _parse_glassdoor_digest(GLASSDOOR_SEPARATE_RATING_HTML, "")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Software Engineer"
    assert job["company"] == "Visa Inc."
    assert job["location"] == "Stockholm"
    # The rating and star must not leak into any field
    for value in (job["title"], job["company"], job["location"]):
        assert value not in ("3.9", "★")


# --- Internal LinkedIn Parser ---

def test_linkedin_parser_skips_header_block():
    """Header block without URL should be skipped."""
    blocks = _parse_linkedin_digest(LINKEDIN_DIGEST)
    # All returned blocks should have URLs
    for block in blocks:
        assert "url" in block
        assert block["url"]


# --- Deduplication via scraped_jobs ---

def test_digest_dedup_by_url(repo):
    """Inserting the same URL twice should not create duplicates."""
    # Must store parent emails first (FK constraint)
    email1 = _make_email(LINKEDIN_DIGEST, email_id="email_1")
    repo.insert_email(email1)
    email2 = _make_email(LINKEDIN_DIGEST, email_id="email_2")
    repo.insert_email(email2)

    jobs = parse_digest(email1)

    inserted_count = 0
    for job in jobs:
        if repo.insert_scraped_job(job):
            inserted_count += 1
    assert inserted_count == 3

    # Insert again (e.g., from a second digest email)
    jobs2 = parse_digest(email2)

    reinserted_count = 0
    for job in jobs2:
        if repo.insert_scraped_job(job):
            reinserted_count += 1
    assert reinserted_count == 0
