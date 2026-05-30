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


def find_negated_keywords(
    text: str,
    negation_phrases: list[str],
    positive_keywords: list[str],
) -> set[str]:
    """Find positive keywords that appear inside matched negation phrases.

    Returns the set of keywords that should be suppressed from positive scoring.
    """
    text_lower = text.lower()
    suppressed: set[str] = set()
    for phrase in negation_phrases:
        if _word_match(phrase, text_lower):
            phrase_lower = phrase.lower()
            for keyword in positive_keywords:
                if _word_match(keyword.lower(), phrase_lower):
                    suppressed.add(keyword.lower())
    return suppressed


# --- Scoring constants ---
TOP_KEYWORD_MATCHES = 3
NEUTRAL_SCORE = 0.5
SENIORITY_POSITIVE_BLEND = 0.5
SALARY_MATCH_SCORE = 0.8
SALARY_LOW_SCORE = 0.3
SALARY_LOW_MARGIN = 0.75
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


def _extract_max_salary(match: re.Match) -> int | None:
    """Extract the maximum salary value from a regex match.

    Handles full numbers (60,000) and k-notation (60k).
    Reconstructs numbers from paired regex groups (integer + thousands).
    Returns the higher end of the range, or None if parsing fails.
    """
    groups = match.groups()
    numbers: list[int] = []
    i = 0
    while i < len(groups):
        g = groups[i]
        if g is None:
            i += 1
            continue
        cleaned = g.replace(",", "").replace(".", "")
        if not cleaned.isdigit():
            i += 1
            continue
        val = int(cleaned)
        # Check if next group is the thousands part of this number
        if i + 1 < len(groups) and groups[i + 1] is not None:
            next_cleaned = groups[i + 1].replace(",", "").replace(".", "")
            if next_cleaned.isdigit() and len(next_cleaned) == 3:
                val = val * 1000 + int(next_cleaned)
                i += 2
                numbers.append(val)
                continue
        if val < 1000:
            val *= 1000
        numbers.append(val)
        i += 1
    return max(numbers) if numbers else None


def score_salary(
    text: str,
    salary_patterns: list[str] | None = None,
    salary_min: int | None = None,
) -> float:
    """Score 0.0-1.0 based on salary information.

    Returns:
        0.5 — no salary mentioned (neutral)
        0.3 — salary found but below min * 0.75 (too low)
        0.8 — salary found and meets or exceeds threshold
    """
    if not text:
        return NEUTRAL_SCORE
    if salary_patterns is None:
        from jobpilot.classifier.signals import SALARY_PATTERNS
        salary_patterns = SALARY_PATTERNS
    text_lower = text.lower()

    for pattern in salary_patterns:
        match = re.search(pattern, text_lower)
        if match:
            if salary_min is None:
                return SALARY_MATCH_SCORE
            max_salary = _extract_max_salary(match)
            if max_salary is None:
                return SALARY_MATCH_SCORE
            if max_salary < salary_min * SALARY_LOW_MARGIN:
                return SALARY_LOW_SCORE
            return SALARY_MATCH_SCORE

    return NEUTRAL_SCORE


def score_negatives(
    text: str,
    negatives: list[str] | None = None,
    negation_phrases: list[str] | None = None,
) -> float:
    """Score 0.0-1.0 where 1.0 means NO negative signals (good)."""
    if not text:
        return 1.0
    if negatives is None:
        from jobpilot.classifier.signals import NEGATIVE_SIGNALS
        negatives = NEGATIVE_SIGNALS
    text_lower = text.lower()

    count = sum(1 for neg in negatives if _word_match(neg, text_lower))
    if negation_phrases:
        count += sum(1 for p in negation_phrases if _word_match(p, text_lower))

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

    # Negation phrases — add to negatives and suppress overlapping positives
    if config.negation_phrases:
        for phrase in config.negation_phrases:
            if _word_match(phrase, text_lower):
                negative.append(phrase)
                phrase_lower = phrase.lower()
                positive = [
                    kw for kw in positive
                    if not _word_match(kw.lower(), phrase_lower)
                ]

    return {"positive": sorted(set(positive)), "negative": sorted(set(negative))}
