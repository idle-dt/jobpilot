"""Tests for the rule-based scoring engine."""

import re

from jobpilot.classifier.features import (
    _extract_max_salary,
    score_job_title,
    score_location,
    score_negatives,
    score_salary,
    score_seniority,
    score_tech_stack,
)
from jobpilot.classifier.rules import RuleBasedScorer
from jobpilot.classifier.signals import SALARY_PATTERNS

# --- Feature Scoring ---

def test_tech_stack_flutter_dart():
    score = score_tech_stack("Flutter and Dart developer needed")
    assert score >= 0.9


def test_tech_stack_no_match():
    score = score_tech_stack("Looking for a Python backend developer")
    assert score == 0.0


def test_tech_stack_secondary():
    score = score_tech_stack("Android and iOS developer")
    assert 0.5 < score < 1.0


def test_location_target():
    assert score_location("Office in Amsterdam, Netherlands") == 1.0


def test_location_remote():
    assert score_location("Fully remote position") == 0.9


def test_location_negative():
    assert score_location("US only, must be located in California") == 0.0


def test_location_no_match():
    assert score_location("Great opportunity") == 0.0


def test_seniority_senior():
    score = score_seniority("Senior Mobile Engineer")
    assert score >= 0.9


def test_seniority_junior():
    score = score_seniority("Junior developer position")
    assert score < 0.5


def test_seniority_unknown():
    assert score_seniority("Developer role") == 0.5


def test_salary_present():
    assert score_salary("Salary: €80,000 - €110,000") == 0.8


def test_salary_absent():
    assert score_salary("Great opportunity") == 0.5


def test_salary_above_threshold():
    assert score_salary("Salary: €80,000 - €110,000", salary_min=60000) == 0.8


def test_salary_below_threshold():
    assert score_salary("Salary: €10,000 - €14,000", salary_min=60000) == 0.3


def test_salary_k_notation_above():
    assert score_salary("60k-80k EUR", salary_min=60000) == 0.8


def test_salary_no_min_still_matches():
    """Without salary_min, any salary mention scores 0.8."""
    assert score_salary("Salary: €12,000 - €14,000") == 0.8


def test_extract_max_salary_range():
    match = re.search(SALARY_PATTERNS[0], "€80,000 - €110,000")
    assert match is not None
    assert _extract_max_salary(match) == 110000


def test_extract_max_salary_k_notation():
    match = re.search(SALARY_PATTERNS[4], "60k-80k eur")
    assert match is not None
    assert _extract_max_salary(match) == 80000


def test_extract_max_salary_non_round_thousands():
    """Non-round thousands like €80,500 must reconstruct correctly."""
    match = re.search(SALARY_PATTERNS[0], "€80,500 - €110,000")
    assert match is not None
    assert _extract_max_salary(match) == 110000


def test_salary_at_boundary():
    """Salary exactly at min * 0.75 should score as match (not low)."""
    assert score_salary("Salary: €40,000 - €45,000", salary_min=60000) == 0.8


def test_negatives_none():
    assert score_negatives("Great Flutter role in Amsterdam") == 1.0


def test_negatives_one():
    assert score_negatives("No visa sponsorship available") == 0.4


def test_negatives_multiple():
    score = score_negatives("No visa sponsorship, security clearance required")
    assert score <= 0.2


def test_job_title_exact():
    assert score_job_title("Senior Flutter Developer") == 1.0


def test_job_title_weak():
    assert score_job_title("Software Engineer") == 0.4


def test_job_title_no_match():
    assert score_job_title("Chef needed") == 0.0


# --- Word Boundary Matching ---

def test_word_boundary_intern():
    """'internet' should NOT match 'intern' signal."""
    score = score_tech_stack("Internet of Things platform")
    assert score == 0.0
    score = score_seniority("Internet Engineer")
    assert score == 0.5  # neutral — no seniority match


def test_word_boundary_lead():
    """'leading' should NOT match 'lead' seniority signal."""
    score = score_seniority("Leading technology company")
    assert score == 0.5  # neutral


def test_word_boundary_ios():
    """'curious' should NOT match 'ios' tech signal."""
    score = score_tech_stack("We want curious engineers")
    assert score == 0.0


def test_word_boundary_staff():
    """'staffing' should NOT match 'staff' seniority signal."""
    score = score_seniority("Staffing agency recruiter")
    assert score == 0.5  # neutral


def test_word_boundary_dart():
    """'dartboard' should NOT match 'dart' tech signal."""
    score = score_tech_stack("Office has a dartboard")
    assert score == 0.0


def test_word_boundary_sr_dot():
    """'sr.' should match as seniority signal."""
    score = score_seniority("Sr. Mobile Engineer")
    assert score >= 0.9


# --- Title-Scoped Seniority ---

def test_seniority_not_matched_in_body():
    """'mentoring interns' in body should NOT trigger negative seniority."""
    scorer = RuleBasedScorer()
    result = scorer.score(
        "Mobile Engineer",
        "You will be mentoring interns and junior developers as part of the team."
    )
    # Seniority should be neutral (0.5), not penalized
    assert result.breakdown["seniority_match"] == 0.5


# --- Full Scorer ---

def test_scorer_high_score():
    scorer = RuleBasedScorer()
    result = scorer.score(
        "Senior Flutter Developer - Amsterdam",
        "We're hiring a senior Flutter developer in Amsterdam, Netherlands. "
        "Tech stack: Flutter, Dart, Kotlin. Salary: €80k-110k EUR. Fully remote option."
    )
    assert result.classification == "worth_checking"
    assert result.score >= 0.7


def test_scorer_low_score():
    scorer = RuleBasedScorer()
    result = scorer.score(
        "Junior Python Backend Developer - US Only",
        "Entry-level Python developer position. US only, no visa sponsorship. "
        "Must have security clearance."
    )
    assert result.classification == "skip"
    assert result.score < 0.5


def test_scorer_medium_score():
    scorer = RuleBasedScorer()
    result = scorer.score(
        "Mobile Developer",
        "Looking for a mobile developer. Android and iOS experience preferred."
    )
    # Should have some score but not necessarily high
    assert 0.0 < result.score < 1.0
    assert result.breakdown is not None
