"""Structural feature extraction for noise model classification."""

from __future__ import annotations

import re

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
