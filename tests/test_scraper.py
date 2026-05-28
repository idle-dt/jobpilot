"""Tests for confidence-based scraping feature."""

from unittest.mock import MagicMock, patch

import pytest
from jobpilot.classifier.rules import RuleBasedScorer, ScoringResult
from jobpilot.scraper.job_page import JobPageScraper
from jobpilot.storage.models import ScrapedJob

# --- Confidence Calculation ---


def test_confidence_at_threshold():
    """Score right on the decision boundary should have zero confidence."""
    scorer = RuleBasedScorer()
    # We can't control the exact score, but we can test the formula directly
    result = scorer.score(
        "Software Engineer",
        "Looking for a software engineer.",
    )
    expected_confidence = min(abs(result.score - 0.6) / 0.4, 1.0)
    assert result.confidence == pytest.approx(expected_confidence, abs=0.01)


def test_confidence_high_score():
    """High match score should have high confidence."""
    scorer = RuleBasedScorer()
    result = scorer.score(
        "Senior Flutter Developer - Amsterdam",
        "Senior Flutter and Dart developer in Amsterdam, Netherlands. Salary: 100k EUR.",
    )
    assert result.score >= 0.7
    assert result.confidence > 0.2


def test_confidence_low_score():
    """Clear skip should have high confidence."""
    scorer = RuleBasedScorer()
    result = scorer.score(
        "Junior Python Backend Developer - US Only",
        "Entry-level Python developer. US only, no visa sponsorship. Security clearance required.",
    )
    assert result.score < 0.5
    assert result.confidence > 0.2


def test_confidence_capped_at_one():
    """Confidence should never exceed 1.0."""
    scorer = RuleBasedScorer()
    result = scorer.score(
        "Senior Flutter Developer - Amsterdam",
        "Senior Flutter and Dart developer in Amsterdam, Netherlands. "
        "Salary: 100k EUR. Fully remote.",
    )
    assert result.confidence <= 1.0


def test_scoring_result_has_confidence():
    """ScoringResult dataclass should include confidence field."""
    result = ScoringResult(score=0.8, classification="worth_checking", breakdown={}, confidence=0.5)
    assert result.confidence == 0.5


# --- Repository Methods ---


def test_update_scraped_job_description(repo):
    job = ScrapedJob(id=None, source="linkedin", title="Test Job", url="https://example.com/1")
    repo.insert_scraped_job(job)

    rows = repo.conn.execute("SELECT id FROM scraped_jobs").fetchall()
    job_id = rows[0]["id"]

    repo.update_scraped_job_description(job_id, "Full job description text here")
    row = repo.conn.execute(
        "SELECT description FROM scraped_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    assert row["description"] == "Full job description text here"


def test_mark_scrape_attempted(repo):
    job = ScrapedJob(id=None, source="linkedin", title="Test Job", url="https://example.com/2")
    repo.insert_scraped_job(job)

    rows = repo.conn.execute("SELECT id FROM scraped_jobs").fetchall()
    job_id = rows[0]["id"]

    repo.mark_scrape_attempted(job_id)
    row = repo.conn.execute(
        "SELECT scrape_attempted FROM scraped_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    assert bool(row["scrape_attempted"]) is True


def test_get_jobs_needing_scrape(repo):
    """Should return LinkedIn/Glassdoor jobs that haven't been scraped."""
    linkedin_job = ScrapedJob(
        id=None, source="linkedin", title="Test Job",
        url="https://www.linkedin.com/jobs/view/123",
    )
    glassdoor_job = ScrapedJob(
        id=None, source="glassdoor", title="Test Job 2",
        url="https://www.glassdoor.com/job/456",
    )
    other_job = ScrapedJob(
        id=None, source="other", title="Test Job 3",
        url="https://example.com/job/789",
    )
    repo.insert_scraped_job(linkedin_job)
    repo.insert_scraped_job(glassdoor_job)
    repo.insert_scraped_job(other_job)

    rows = repo.conn.execute("SELECT id, url FROM scraped_jobs").fetchall()
    for r in rows:
        repo.update_scraped_job_scores(r["id"], 0.7, None, "worth_checking")

    # Also add a lookalike domain that should NOT match
    fake_job = ScrapedJob(
        id=None, source="other", title="Fake Job",
        url="https://fakelinkedin.com/jobs/view/000",
    )
    repo.insert_scraped_job(fake_job)
    rows2 = repo.conn.execute(
        "SELECT id FROM scraped_jobs WHERE url LIKE '%fakelinkedin%'"
    ).fetchall()
    repo.update_scraped_job_scores(rows2[0]["id"], 0.7, None, "worth_checking")

    needing = repo.get_jobs_needing_scrape()
    urls = {j.url for j in needing}
    assert "https://www.linkedin.com/jobs/view/123" in urls
    assert "https://www.glassdoor.com/job/456" in urls
    assert "https://example.com/job/789" not in urls
    assert "https://fakelinkedin.com/jobs/view/000" not in urls


def test_get_jobs_needing_scrape_excludes_attempted(repo):
    job = ScrapedJob(
        id=None, source="linkedin", title="Test Job",
        url="https://www.linkedin.com/jobs/view/999",
    )
    repo.insert_scraped_job(job)
    rows = repo.conn.execute("SELECT id FROM scraped_jobs").fetchall()
    job_id = rows[0]["id"]

    repo.update_scraped_job_scores(job_id, 0.55, None, "skip")
    repo.mark_scrape_attempted(job_id)

    needing = repo.get_jobs_needing_scrape()
    assert len(needing) == 0


def test_get_jobs_needing_scrape_requires_score(repo):
    """Unscored jobs (score IS NULL) should not appear in scrape queue."""
    job = ScrapedJob(
        id=None, source="linkedin", title="Unscored Job",
        url="https://www.linkedin.com/jobs/view/unscored",
    )
    repo.insert_scraped_job(job)
    # score is NULL by default — should not appear
    needing = repo.get_jobs_needing_scrape()
    assert len(needing) == 0


def test_toggle_scraped_job_expired(repo):
    """toggle_scraped_job_expired should flip the expired flag."""
    job = ScrapedJob(
        id=None, source="linkedin", title="Expired Job",
        url="https://www.linkedin.com/jobs/view/expired",
    )
    repo.insert_scraped_job(job)
    rows = repo.conn.execute("SELECT id FROM scraped_jobs").fetchall()
    job_id = rows[0]["id"]

    # First toggle: False -> True
    new_val = repo.toggle_scraped_job_expired(job_id)
    assert new_val is True

    row = repo.conn.execute(
        "SELECT expired FROM scraped_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    assert bool(row["expired"]) is True

    # Second toggle: True -> False
    new_val = repo.toggle_scraped_job_expired(job_id)
    assert new_val is False


def test_row_to_scraped_job_includes_new_fields(repo):
    job = ScrapedJob(id=None, source="linkedin", title="Test Job", url="https://example.com/6")
    repo.insert_scraped_job(job)
    rows = repo.conn.execute("SELECT id FROM scraped_jobs").fetchall()
    job_id = rows[0]["id"]

    repo.update_scraped_job_description(job_id, "Some description")
    repo.mark_scrape_attempted(job_id)

    jobs = repo.get_scraped_jobs_for_review(limit=10)
    found = [j for j in jobs if j.id == job_id]
    assert len(found) == 1
    assert found[0].description == "Some description"
    assert found[0].scrape_attempted is True


# --- JobPageScraper ---


def test_scraper_generic_html():
    scraper = JobPageScraper()
    html = """
    <html>
    <head><title>Job</title></head>
    <body>
    <nav>Navigation</nav>
    <main>
        <div class="job-description">
            <h2>About the Role</h2>
            <p>We are looking for a Senior Flutter Developer to join our team in Amsterdam.</p>
            <p>Requirements: 5+ years of experience with Flutter and Dart.</p>
            <p>Benefits: Remote work, competitive salary, relocation support.</p>
        </div>
    </main>
    <footer>Footer</footer>
    </body>
    </html>
    """
    result = scraper._parse_generic(html)
    assert result is not None
    assert "Flutter Developer" in result
    assert "Navigation" not in result
    assert "Footer" not in result


def test_scraper_linkedin_html():
    scraper = JobPageScraper()
    html = """
    <html>
    <body>
    <div class="description__text">
        <p>Senior Flutter Developer needed for exciting project in Amsterdam.</p>
        <p>Tech: Flutter, Dart, Firebase. Salary: 90-120k EUR.</p>
    </div>
    </body>
    </html>
    """
    result = scraper._parse_linkedin(html)
    assert result is not None
    assert "Flutter Developer" in result


@patch("jobpilot.scraper.job_page.is_safe_url", return_value=True)
@patch("jobpilot.scraper.job_page.requests.get")
def test_scraper_fetch_failure(mock_get, _mock_safe):
    """Scrape should return None on network failure."""
    import requests

    mock_get.side_effect = requests.ConnectionError("Connection refused")
    scraper = JobPageScraper()
    result = scraper.scrape("https://example.com/job/123")
    assert result is None


@patch("jobpilot.scraper.job_page.is_safe_url", return_value=True)
@patch("jobpilot.scraper.job_page.requests.get")
def test_scraper_routes_to_linkedin(mock_get, _mock_safe):
    """Should use LinkedIn parser for LinkedIn URLs."""
    mock_resp = MagicMock()
    mock_resp.text = '<div class="description__text"><p>Flutter role</p></div>'
    mock_resp.raise_for_status = MagicMock()
    mock_resp.is_redirect = False
    mock_get.return_value = mock_resp

    scraper = JobPageScraper()
    result = scraper.scrape("https://linkedin.com/jobs/view/12345")
    assert result is not None
    assert "Flutter" in result


def test_is_safe_url_rejects_private():
    """Should reject dangerous schemes and allow valid HTTPS URLs."""
    from jobpilot.scraper.job_page import is_safe_url

    assert is_safe_url("https://www.linkedin.com/jobs/view/1") is True
    assert is_safe_url("http://example.com/job") is True
    assert is_safe_url("javascript:alert(1)") is False
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("ftp://example.com") is False
    assert is_safe_url("") is False
    assert is_safe_url("http://127.0.0.1/") is False
    assert is_safe_url("http://192.168.1.1/job") is False


# --- Domain Routing ---


def test_get_scrapable_domain_linkedin():
    """Should match linkedin.com and subdomains."""
    from jobpilot.services.sync_service import _get_scrapable_domain

    assert _get_scrapable_domain("https://www.linkedin.com/jobs/view/1") == "linkedin.com"
    assert _get_scrapable_domain("https://de.linkedin.com/jobs/view/2") == "linkedin.com"
    assert _get_scrapable_domain("https://linkedin.com/jobs/view/3") == "linkedin.com"


def test_get_scrapable_domain_glassdoor():
    """Should match glassdoor.com and subdomains."""
    from jobpilot.services.sync_service import _get_scrapable_domain

    assert _get_scrapable_domain("https://www.glassdoor.com/job/1") == "glassdoor.com"
    assert _get_scrapable_domain("https://glassdoor.com/job/2") == "glassdoor.com"


def test_get_scrapable_domain_rejects_others():
    """Should return None for non-scrapable domains."""
    from jobpilot.services.sync_service import _get_scrapable_domain

    assert _get_scrapable_domain("https://example.com/job/1") is None
    assert _get_scrapable_domain("https://fakelinkedin.com/jobs/1") is None
    assert _get_scrapable_domain("https://indeed.com/job/1") is None
    assert _get_scrapable_domain("not-a-url") is None


# --- BrowserScraper ---


@patch("jobpilot.scraper.browser.is_safe_url", return_value=False)
def test_browser_scraper_rejects_unsafe_url(_mock_safe):
    """BrowserScraper.scrape should return None for unsafe URLs."""
    from jobpilot.scraper.browser import BrowserScraper

    scraper = BrowserScraper()
    result = scraper.scrape("javascript:alert(1)")
    assert result is None
    scraper.close()


def test_browser_scraper_close_noop():
    """close() should be safe to call when context was never created."""
    from jobpilot.scraper.browser import BrowserScraper

    scraper = BrowserScraper()
    scraper.close()  # must not raise


def test_browser_extract_for_domain_routes_linkedin():
    """_extract_for_domain should route linkedin.com to _extract_linkedin."""
    from jobpilot.scraper.browser import BrowserScraper

    scraper = BrowserScraper()
    mock_page = MagicMock()

    with patch.object(scraper, "_extract_linkedin", return_value="LinkedIn desc") as mock_li:
        result = scraper._extract_for_domain(mock_page, "www.linkedin.com")
    assert result == "LinkedIn desc"
    mock_li.assert_called_once_with(mock_page)


def test_browser_extract_for_domain_routes_generic():
    """_extract_for_domain should route non-LinkedIn to _extract_generic."""
    from jobpilot.scraper.browser import BrowserScraper

    scraper = BrowserScraper()
    mock_page = MagicMock()

    with patch.object(scraper, "_extract_generic", return_value="Generic desc") as mock_gen:
        result = scraper._extract_for_domain(mock_page, "www.glassdoor.com")
    assert result == "Generic desc"
    mock_gen.assert_called_once_with(mock_page)
