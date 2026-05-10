"""Feature extraction for classification scoring."""

import re


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
        if keyword in text_lower:
            matched_weights.append(info["weight"])

    if not matched_weights:
        return 0.0
    # Average of top 3 matches, capped at 1.0
    top = sorted(matched_weights, reverse=True)[:3]
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
        if location in text_lower:
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
        return 0.5  # Unknown seniority is neutral
    if patterns is None:
        from jobpilot.classifier.signals import SENIORITY_PATTERNS
        patterns = SENIORITY_PATTERNS
    text_lower = text.lower()

    for pattern, info in patterns.items():
        if pattern in text_lower:
            weight = info["weight"]
            if weight < 0:
                return max(0.0, 0.5 + weight)
            return min(0.5 + weight * 0.5, 1.0)

    return 0.5  # No seniority info = neutral


def score_salary(text: str, salary_patterns: list[str] | None = None) -> float:
    """Score 0.0-1.0 based on salary information."""
    if not text:
        return 0.5  # No salary info = neutral
    if salary_patterns is None:
        from jobpilot.classifier.signals import SALARY_PATTERNS
        salary_patterns = SALARY_PATTERNS
    text_lower = text.lower()

    for pattern in salary_patterns:
        match = re.search(pattern, text_lower)
        if match:
            return 0.8  # Has salary info = positive signal

    return 0.5


def score_negatives(text: str, negatives: list[str] | None = None) -> float:
    """Score 0.0-1.0 where 1.0 means NO negative signals (good)."""
    if not text:
        return 1.0
    if negatives is None:
        from jobpilot.classifier.signals import NEGATIVE_SIGNALS
        negatives = NEGATIVE_SIGNALS
    text_lower = text.lower()

    count = sum(1 for neg in negatives if neg in text_lower)
    if count == 0:
        return 1.0
    if count == 1:
        return 0.4
    return 0.1


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
        if title in text_lower:
            best_weight = max(best_weight, info["weight"])

    return best_weight
