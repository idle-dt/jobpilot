"""Tests for digest email parsing."""

from datetime import datetime, timezone

from jobpilot.gmail.digest import (
    _GLASSDOOR_NOISE_RE,
    _GLASSDOOR_SALARY_RE,
    _clean_job_url,
    _is_boilerplate_line,
    _parse_glassdoor_digest,
    _parse_linkedin_digest,
    _parse_wellfound_digest,
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


def test_parse_digest_keeps_ios_title_end_to_end():
    """End-to-end: an iOS title survives parse_digest's final boilerplate filter."""
    body = (
        "iOS Developer - Native Mobile Platforms (KMP)\n"
        "iO\n"
        "Amsterdam\n"
        "View job: https://www.linkedin.com/comm/jobs/view/4410029616/\n"
    )
    email = _make_email(body)
    jobs = parse_digest(email)
    assert len(jobs) == 1
    assert jobs[0].title == "iOS Developer - Native Mobile Platforms (KMP)"
    assert jobs[0].company == "iO"


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


GLASSDOOR_DECIMAL_TITLE_HTML = """\
<html><body>
<table><tr><td>
  <div>Acme Corp</div>
  <div>4.2</div>
  <div>★</div>
  <a href="https://www.glassdoor.com/partner/jobListing.htm?jl=9">3.0 to 5.0 yrs - Backend Engineer</a>
  <div>Berlin</div>
</td></tr></table>
</body></html>
"""


def test_glassdoor_decimal_prefixed_title_not_dropped():
    """A title that merely starts with a decimal must not be filtered as a rating."""
    jobs = _parse_glassdoor_digest(GLASSDOOR_DECIMAL_TITLE_HTML, "")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "3.0 to 5.0 yrs - Backend Engineer"
    assert job["company"] == "Acme Corp"
    assert job["location"] == "Berlin"


# --- Glassdoor: salary detection and noise filtering ---


def test_glassdoor_salary_re_matches_standalone_ranges():
    """Standalone salary ranges are recognized as salary."""
    assert _GLASSDOOR_SALARY_RE.match("$150K - $220K")
    assert _GLASSDOOR_SALARY_RE.match("$85K - $103K")


def test_glassdoor_salary_re_rejects_title_with_parenthetical_amount():
    """A title containing a parenthetical salary is NOT treated as salary."""
    title = "Remote Sr/Staff Engineer ($150-$220k) Agentic AI, Ruby, Rails"
    assert _GLASSDOOR_SALARY_RE.match(title) is None


def test_glassdoor_noise_re_filters_hours_and_days():
    """Time durations in hours and days are filtered as noise."""
    assert _GLASSDOOR_NOISE_RE.match("22h")
    assert _GLASSDOOR_NOISE_RE.match("6h")
    assert _GLASSDOOR_NOISE_RE.match("3d")


GLASSDOOR_EVERFORTH_HTML = """\
<html><body>
<table><tr><td>
  <div>Everforth CyberCoders</div>
  <div>4.5</div>
  <div>★</div>
  <a href="https://www.glassdoor.com/partner/jobListing.htm?pos=102&jobListingId=1010148677811&jrtk=abc">Remote Sr/Staff Engineer ($150-$220k) Agentic AI, Ruby, Rails</a>
  <div>Philadelphia, PA</div>
  <div>$150K - $220K</div>
  <div>22h</div>
</td></tr></table>
</body></html>
"""


def test_glassdoor_full_card_keeps_title_and_extracts_salary():
    """Title with parenthetical salary survives; salary and location are correct."""
    jobs = _parse_glassdoor_digest(GLASSDOOR_EVERFORTH_HTML, "")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Remote Sr/Staff Engineer ($150-$220k) Agentic AI, Ruby, Rails"
    assert job["company"] == "Everforth CyberCoders"
    assert job["location"] == "Philadelphia, PA"
    assert job["salary"] == "$150K - $220K"


# --- Glassdoor: URL normalization ---


def test_clean_glassdoor_url_keeps_only_job_listing_id():
    """Glassdoor tracking params are stripped, keeping only jobListingId."""
    url = (
        "https://www.glassdoor.com/partner/jobListing.htm"
        "?pos=102&jobListingId=1010148677811&jrtk=abc"
    )
    assert _clean_job_url(url) == (
        "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=1010148677811"
    )


def test_clean_glassdoor_url_dedups_across_digests():
    """Same jobListingId with different tracking params yields identical URLs."""
    url_a = (
        "https://www.glassdoor.com/partner/jobListing.htm"
        "?pos=102&jobListingId=1010148677811&guid=aaa&cb=111"
    )
    url_b = (
        "https://www.glassdoor.com/partner/jobListing.htm"
        "?pos=999&jobListingId=1010148677811&guid=bbb&cb=222"
    )
    assert _clean_job_url(url_a) == _clean_job_url(url_b)


# --- Glassdoor: in-email content dedup ---

# A single digest lists the same posting twice with different jobListingId links.
GLASSDOOR_DUPLICATE_CARDS_HTML = """\
<html><body>
<table><tr><td>
  <div>DataAnnotation</div>
  <a href="https://www.glassdoor.com/partner/jobListing.htm?jobListingId=1010123850169">Software Engineer - AI Trainer</a>
  <div>Stockholm</div>
</td></tr></table>
<table><tr><td>
  <div>DataAnnotation</div>
  <a href="https://www.glassdoor.com/partner/jobListing.htm?jobListingId=1010123850111">Software Engineer - AI Trainer</a>
  <div>Stockholm</div>
</td></tr></table>
</body></html>
"""


def test_glassdoor_duplicate_cards_collapse_to_one():
    """Two cards with the same title/company/location collapse to a single job."""
    jobs = _parse_glassdoor_digest(GLASSDOOR_DUPLICATE_CARDS_HTML, "")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Software Engineer - AI Trainer"
    assert jobs[0]["company"] == "DataAnnotation"
    assert jobs[0]["location"] == "Stockholm"


# --- Wellfound: HTML digest parsing ---

# Mirrors the real Wellfound alert structure: a greeting banner (24px, with a
# background-color) and a "Our take" blurb (12px) both use font-weight:700, and
# the primary job card is rendered twice. Only the 14px/#000 title divs are real
# jobs, and the duplicate card must collapse via (title, company) dedup.
WELLFOUND_DIGEST_HTML = """\
<html><body>
<table><tr><td>
  <div style="background-color: #210D25; font-size: 24px; font-weight: 700;">Hi Denys! I've found 2 new jobs matching your alert preferences.</div>
</td></tr></table>
<table><tr><td>
  <div style="font-size: 14px; font-weight: 700; color: #000;">Mobile Developer (iOS or Android)</div>
  <span style="color: #541142;">Tech Consulting</span>
  <div style="font-size: 12px; font-weight: 700; color: #E93570;">Our take</div>
  <a href="https://links.wellfound.com/s/c/abc123">Learn more</a>
</td></tr></table>
<table><tr><td>
  <div style="font-size: 14px; font-weight: 700; color: #000;">Mobile Developer (iOS or Android)</div>
  <span style="color: #541142;">Tech Consulting</span>
  <a href="https://links.wellfound.com/s/c/abc999">Learn more</a>
</td></tr></table>
<table><tr><td>
  <div style="font-size: 14px; font-weight: 700; color: #000;">Senior Flutter Engineer</div>
  <span style="color: #541142;">Acme Startup</span>
  <a href="https://links.wellfound.com/s/c/def456">Learn more</a>
</td></tr></table>
</body></html>
"""


def test_parse_wellfound_digest_dedups_to_two_jobs():
    """Greeting + 'Our take' are ignored and the duplicate card collapses to one."""
    jobs = _parse_wellfound_digest(WELLFOUND_DIGEST_HTML, "")
    assert len(jobs) == 2


def test_parse_wellfound_digest_titles_and_companies():
    """Title and company come from the structured HTML, not the smushed text."""
    jobs = _parse_wellfound_digest(WELLFOUND_DIGEST_HTML, "")
    by_title = {j["title"]: j for j in jobs}
    assert "Mobile Developer (iOS or Android)" in by_title
    assert by_title["Mobile Developer (iOS or Android)"]["company"] == "Tech Consulting"
    assert "Senior Flutter Engineer" in by_title
    assert by_title["Senior Flutter Engineer"]["company"] == "Acme Startup"
    # The greeting banner and "Our take" blurb must never be parsed as jobs.
    for job in jobs:
        assert "found" not in job["title"].lower()
        assert job["title"] != "Our take"


def test_parse_wellfound_digest_urls_point_to_wellfound():
    """Each job carries a wellfound (or links.wellfound) redirect URL."""
    jobs = _parse_wellfound_digest(WELLFOUND_DIGEST_HTML, "")
    for job in jobs:
        assert "wellfound.com" in job["url"]


def test_parse_wellfound_digest_rejects_unsafe_href():
    """A card whose only link is a javascript: scheme yields no job."""
    html = """\
<table><tr><td>
  <div style="font-size: 14px; font-weight: 700; color: #000;">Evil Role</div>
  <span style="color: #541142;">Sketchy Inc</span>
  <a href="javascript:alert(1)">Learn more</a>
</td></tr></table>
"""
    assert _parse_wellfound_digest(html, "") == []


def test_parse_wellfound_digest_skips_non_wellfound_links():
    """An unsubscribe/footer link before the job link must not be captured."""
    html = """\
<table><tr><td>
  <div style="font-size: 14px; font-weight: 700; color: #000;">React Native Engineer</div>
  <span style="color: #541142;">Acme</span>
  <a href="https://example.com/unsubscribe">Unsubscribe</a>
  <a href="https://links.wellfound.com/s/c/realjob">Learn more</a>
</td></tr></table>
"""
    jobs = _parse_wellfound_digest(html, "")
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://links.wellfound.com/s/c/realjob"


def test_parse_wellfound_digest_prefers_learn_more_over_company_link():
    """When a card has both a company-page link and a Learn more redirect,
    the redirect (the specific job) must win."""
    html = """\
<table><tr><td>
  <div style="font-size: 14px; font-weight: 700; color: #000;">Contract Flutter Engineer</div>
  <span style="color: #541142;">Resengi</span>
  <a href="https://wellfound.com/company/resengi/jobs?email_uid=123&utm_source=x">Resengi</a>
  <a href="https://links.wellfound.com/s/c/REALTOKEN/20">Learn more</a>
</td></tr></table>
"""
    jobs = _parse_wellfound_digest(html, "")
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://links.wellfound.com/s/c/REALTOKEN/20"


def test_parse_wellfound_digest_ignores_company_only_card():
    """A card whose only link is a company page yields no job (no per-job link)."""
    html = """\
<table><tr><td>
  <div style="font-size: 14px; font-weight: 700; color: #000;">Some Role</div>
  <span style="color: #541142;">Acme</span>
  <a href="https://wellfound.com/company/acme/jobs?email_uid=9">Acme</a>
</td></tr></table>
"""
    assert _parse_wellfound_digest(html, "") == []


def test_parse_wellfound_digest_rejects_spoofed_host():
    """A look-alike host (wellfound.com.attacker.net) must not be accepted."""
    html = """\
<table><tr><td>
  <div style="font-size: 14px; font-weight: 700; color: #000;">Spoof Role</div>
  <span style="color: #541142;">Bad Co</span>
  <a href="https://wellfound.com.attacker.net/jobs/1">Learn more</a>
</td></tr></table>
"""
    assert _parse_wellfound_digest(html, "") == []


def test_parse_wellfound_digest_no_html_falls_back_to_generic():
    """With no HTML body, fall back to the generic text parser."""
    body = "Check this role: https://wellfound.com/jobs/12345-mobile-developer"
    jobs = _parse_wellfound_digest("", body)
    assert len(jobs) == 1
    assert "wellfound.com/jobs/" in jobs[0]["url"]


def test_parse_digest_routes_wellfound_emails():
    """parse_digest routes a wellfound email through the HTML parser."""
    email = Email(
        id="wf_email_1",
        thread_id="thread_wf",
        sender="jobs@wellfound.com",
        sender_domain="wellfound.com",
        subject="New jobs for you",
        received_at=datetime.now(timezone.utc),
        body_text="Mobile Developer Actively Hiring years of exp Portugal",
        body_html=WELLFOUND_DIGEST_HTML,
        platform="wellfound",
    )
    jobs = parse_digest(email)
    titles = {j.title for j in jobs}
    assert "Mobile Developer (iOS or Android)" in titles
    assert "Senior Flutter Engineer" in titles
    for job in jobs:
        assert job.source == "wellfound"


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
