"""Tests for confidence-based scraping feature."""

from unittest.mock import MagicMock, patch

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
    assert result.confidence == round(expected_confidence, 3)


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
    # Insert a job with an ambiguous score (close to threshold 0.6)
    job = ScrapedJob(id=None, source="linkedin", title="Test Job", url="https://example.com/3")
    repo.insert_scraped_job(job)
    rows = repo.conn.execute("SELECT id FROM scraped_jobs").fetchall()
    job_id = rows[0]["id"]

    # Set score near the threshold (0.6) -> low confidence
    repo.update_scraped_job_scores(job_id, 0.55, None, "skip")

    # Should be found with default thresholds
    needing = repo.get_jobs_needing_scrape(score_threshold=0.6, confidence_threshold=0.5)
    assert len(needing) == 1
    assert needing[0].id == job_id


def test_get_jobs_needing_scrape_excludes_attempted(repo):
    job = ScrapedJob(id=None, source="linkedin", title="Test Job", url="https://example.com/4")
    repo.insert_scraped_job(job)
    rows = repo.conn.execute("SELECT id FROM scraped_jobs").fetchall()
    job_id = rows[0]["id"]

    repo.update_scraped_job_scores(job_id, 0.55, None, "skip")
    repo.mark_scrape_attempted(job_id)

    needing = repo.get_jobs_needing_scrape(score_threshold=0.6, confidence_threshold=0.5)
    assert len(needing) == 0


def test_get_jobs_needing_scrape_excludes_high_confidence(repo):
    job = ScrapedJob(id=None, source="linkedin", title="Test Job", url="https://example.com/5")
    repo.insert_scraped_job(job)
    rows = repo.conn.execute("SELECT id FROM scraped_jobs").fetchall()
    job_id = rows[0]["id"]

    # Score far from threshold -> high confidence
    repo.update_scraped_job_scores(job_id, 0.95, None, "worth_checking")

    needing = repo.get_jobs_needing_scrape(score_threshold=0.6, confidence_threshold=0.5)
    assert len(needing) == 0


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


def test_scraper_indeed_html():
    scraper = JobPageScraper()
    html = """
    <html>
    <body>
    <div id="jobDescriptionText">
        <p>Mobile Developer role. Experience with Android and iOS required.</p>
        <p>Location: Netherlands. Remote possible.</p>
    </div>
    </body>
    </html>
    """
    result = scraper._parse_indeed(html)
    assert result is not None
    assert "Mobile Developer" in result


@patch("jobpilot.scraper.job_page._is_safe_url", return_value=True)
@patch("jobpilot.scraper.job_page.requests.get")
def test_scraper_fetch_failure(mock_get, _mock_safe):
    """Scrape should return None on network failure."""
    import requests

    mock_get.side_effect = requests.ConnectionError("Connection refused")
    scraper = JobPageScraper()
    result = scraper.scrape("https://example.com/job/123")
    assert result is None


@patch("jobpilot.scraper.job_page._is_safe_url", return_value=True)
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
    """Should reject private/loopback URLs."""
    from jobpilot.scraper.job_page import _is_safe_url

    assert _is_safe_url("javascript:alert(1)") is False
    assert _is_safe_url("file:///etc/passwd") is False
    assert _is_safe_url("ftp://example.com") is False
    assert _is_safe_url("") is False
