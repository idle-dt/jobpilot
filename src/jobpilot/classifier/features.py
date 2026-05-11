"""Feature extraction for classification scoring."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jobpilot.classifier.rules import SignalConfig


def _word_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a whole word/phrase in text."""
    escaped = re.escape(keyword)
    if keyword.endswith('.'):
        pattern = r'\b' + escaped
    else:
        pattern = r'\b' + escaped + r'\b'
    return bool(re.search(pattern, text))


# --- Scoring constants ---
TOP_KEYWORD_MATCHES = 3
NEUTRAL_SCORE = 0.5
SENIORITY_POSITIVE_BLEND = 0.5
SALARY_MATCH_SCORE = 0.8
NEGATIVES_ONE_SCORE = 0.4
NEGATIVES_MANY_SCORE = 0.1


def score_tech_stack(text: str, keywords: dict[str, dict] | None = None) -> float:
    """Score 0.0-1.0 based on tech stack keyword matches."""
    if not text:
        return 0.0
    if keywords is None:
        from jobpilot.classifier.signals import TECH_STACK_KEYWORDS
        keywords = TECH_STACK_KEYWORDS
    text_lower = text.lower()
    matched_weights = []
    for keyword, info in keywords.items():
        if _word_match(keyword, text_lower):
            matched_weights.append(info["weight"])

    if not matched_weights:
        return 0.0
    top = sorted(matched_weights, reverse=True)[:TOP_KEYWORD_MATCHES]
    return min(sum(top) / len(top), 1.0)


def score_location(text: str, locations: dict[str, dict] | None = None) -> float:
    """Score 0.0-1.0 based on location matches."""
    if not text:
        return 0.0
    if locations is None:
        from jobpilot.classifier.signals import LOCATION_PATTERNS
        locations = LOCATION_PATTERNS
    text_lower = text.lower()
    best_weight = 0.0
    has_negative = False

    for location, info in locations.items():
        if _word_match(location, text_lower):
            if info["weight"] < 0:
                has_negative = True
            else:
                best_weight = max(best_weight, info["weight"])

    if has_negative and best_weight == 0.0:
        return 0.0
    return best_weight


def score_seniority(text: str, patterns: dict[str, dict] | None = None) -> float:
    """Score 0.0-1.0 based on seniority level match."""
    if not text:
        return NEUTRAL_SCORE
    if patterns is None:
        from jobpilot.classifier.signals import SENIORITY_PATTERNS
        patterns = SENIORITY_PATTERNS
    text_lower = text.lower()

    for pattern, info in patterns.items():
        if _word_match(pattern, text_lower):
            weight = info["weight"]
            if weight < 0:
                return max(0.0, NEUTRAL_SCORE + weight)
            return min(NEUTRAL_SCORE + weight * SENIORITY_POSITIVE_BLEND, 1.0)

    return NEUTRAL_SCORE


def score_salary(text: str, salary_patterns: list[str] | None = None) -> float:
    """Score 0.0-1.0 based on salary information."""
    if not text:
        return NEUTRAL_SCORE
    if salary_patterns is None:
        from jobpilot.classifier.signals import SALARY_PATTERNS
        salary_patterns = SALARY_PATTERNS
    text_lower = text.lower()

    for pattern in salary_patterns:
        match = re.search(pattern, text_lower)
        if match:
            return SALARY_MATCH_SCORE

    return NEUTRAL_SCORE


def score_negatives(text: str, negatives: list[str] | None = None) -> float:
    """Score 0.0-1.0 where 1.0 means NO negative signals (good)."""
    if not text:
        return 1.0
    if negatives is None:
        from jobpilot.classifier.signals import NEGATIVE_SIGNALS
        negatives = NEGATIVE_SIGNALS
    text_lower = text.lower()

    count = sum(1 for neg in negatives if _word_match(neg, text_lower))
    if count == 0:
        return 1.0
    if count == 1:
        return NEGATIVES_ONE_SCORE
    return NEGATIVES_MANY_SCORE


def score_job_title(text: str, titles: dict[str, dict] | None = None) -> float:
    """Score 0.0-1.0 based on job title match."""
    if not text:
        return 0.0
    if titles is None:
        from jobpilot.classifier.signals import TARGET_JOB_TITLES
        titles = TARGET_JOB_TITLES
    text_lower = text.lower()
    best_weight = 0.0

    for title, info in titles.items():
        if _word_match(title, text_lower):
            best_weight = max(best_weight, info["weight"])

    return best_weight


def extract_matched_keywords(
    text: str, config: SignalConfig, subject: str = "",
) -> dict[str, list[str]]:
    """Return positive and negative keyword matches found in text.

    Uses the same keyword dictionaries as the score_* functions.
    Seniority is matched against subject only (title-scoped).
    """
    positive: list[str] = []
    negative: list[str] = []

    if not text:
        return {"positive": positive, "negative": negative}

    text_lower = text.lower()
    subject_lower = subject.lower()

    # Tech stack keywords
    if config.tech_keywords:
        for keyword in config.tech_keywords:
            if _word_match(keyword, text_lower):
                positive.append(keyword)

    # Job titles
    if config.job_titles:
        for title in config.job_titles:
            if _word_match(title, text_lower):
                positive.append(title)

    # Locations — split by weight sign
    if config.locations:
        for location, info in config.locations.items():
            if _word_match(location, text_lower):
                if info["weight"] < 0:
                    negative.append(location)
                else:
                    positive.append(location)

    # Seniority — match only in subject/title, not body
    if config.seniority_patterns and subject_lower:
        for pattern, info in config.seniority_patterns.items():
            if _word_match(pattern, subject_lower):
                if info["weight"] < 0:
                    negative.append(pattern)
                else:
                    positive.append(pattern)

    # Salary matches
    if config.salary_patterns:
        for pat in config.salary_patterns:
            match = re.search(pat, text_lower)
            if match:
                positive.append(match.group(0))

    # Negatives
    if config.negatives:
        for neg in config.negatives:
            if _word_match(neg, text_lower):
                negative.append(neg)

    return {"positive": sorted(set(positive)), "negative": sorted(set(negative))}


# --- Structural features for noise model tiers ---

STRUCTURAL_FEATURE_NAMES_TIER1 = ["digest_job_count", "url_count", "body_length"]
STRUCTURAL_FEATURE_NAMES_TIER2 = [
    "subject_length", "paragraph_count", "company_name_count", "has_salary_mention",
]

# Normalization caps for structural features (max expected value → 1.0)
MAX_DIGEST_JOBS = 20
MAX_URL_COUNT = 20
MAX_BODY_LENGTH = 5000
MAX_SUBJECT_LENGTH = 200
MAX_PARAGRAPH_COUNT = 30
MAX_COMPANY_NAMES = 10

_COMMON_CAPITALIZED = frozenset({
    "Dear", "Hello", "Thank", "Thanks", "Please", "Best", "Regards", "Sincerely",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December", "The", "This", "That", "What",
    "When", "Where", "How", "Your", "Our", "Are", "Not", "New", "You", "We",
    "Click", "View", "See", "Read", "Get", "Apply", "Join", "Sign", "Log",
})


def compute_structural_features(
    subject: str, body_text: str, digest_job_count: int = 0,
) -> dict[str, float]:
    """Compute structural features for noise model.

    Returns dict with all 7 structural feature values normalized to 0.0-1.0.
    """
    features: dict[str, float] = {}

    # Tier 1
    features["digest_job_count"] = min(digest_job_count / MAX_DIGEST_JOBS, 1.0)

    url_matches = re.findall(r'https?://[^\s<>"]+', body_text)
    features["url_count"] = min(len(url_matches) / MAX_URL_COUNT, 1.0)

    features["body_length"] = min(len(body_text) / MAX_BODY_LENGTH, 1.0)

    # Tier 2
    features["subject_length"] = min(len(subject) / MAX_SUBJECT_LENGTH, 1.0)

    para_by_newline = len([p for p in body_text.split("\n\n") if p.strip()])
    para_by_tag = len(re.findall(r"<p[\s>]", body_text, re.IGNORECASE))
    features["paragraph_count"] = min(max(para_by_newline, para_by_tag) / MAX_PARAGRAPH_COUNT, 1.0)

    company_matches = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", body_text)
    distinct_companies = {m for m in company_matches if m.split()[0] not in _COMMON_CAPITALIZED}
    features["company_name_count"] = min(len(distinct_companies) / MAX_COMPANY_NAMES, 1.0)

    from jobpilot.classifier.signals import SALARY_PATTERNS
    text_lower = body_text.lower()
    has_salary = any(re.search(p, text_lower) for p in SALARY_PATTERNS)
    features["has_salary_mention"] = 1.0 if has_salary else 0.0

    return features
