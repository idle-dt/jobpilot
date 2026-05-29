"""Rule-based scoring engine for job email classification."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from jobpilot.classifier.features import (
    find_negated_keywords,
    score_job_title,
    score_location,
    score_negatives,
    score_salary,
    score_seniority,
    score_tech_stack,
)
from jobpilot.classifier.geo import expand_locations
from jobpilot.classifier.signals import JOB_TITLE_SECONDARY_WEIGHT
from jobpilot.config import settings

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "tech_match", "job_title", "location_match",
    "seniority_match", "salary_match", "negative_signals",
]


@dataclass
class SignalConfig:
    """Holds user-configured signal keywords for scoring."""
    tech_keywords: dict[str, dict] | None = None
    job_titles: dict[str, dict] | None = None
    locations: dict[str, dict] | None = None
    seniority_patterns: dict[str, dict] | None = None
    salary_patterns: list[str] | None = None
    salary_min: int | None = None
    salary_currency: str | None = None
    negatives: list[str] | None = None
    negation_phrases: list[str] | None = None


def load_signal_config(repo) -> SignalConfig:
    """Build a SignalConfig from database preferences."""
    prefs = repo.get_all_preferences()

    tech_keywords: dict[str, dict] = {}
    for p in prefs.get("tech_keyword_primary", []):
        tech_keywords[p.value] = {"weight": 1.0, "category": "primary"}
    for p in prefs.get("tech_keyword_secondary", []):
        tech_keywords[p.value] = {"weight": 0.5, "category": "secondary"}

    job_titles: dict[str, dict] = {}
    for p in prefs.get("job_title_primary", []):
        job_titles[p.value] = {"weight": 1.0}
    for p in prefs.get("job_title_secondary", []):
        job_titles[p.value] = {"weight": JOB_TITLE_SECONDARY_WEIGHT}

    locations: dict[str, dict] = {}
    for p in prefs.get("location_primary", []):
        locations[p.value] = {"weight": 1.0, "target": True}
    for p in prefs.get("location_secondary", []):
        locations[p.value] = {"weight": 0.6, "target": False}
    for p in prefs.get("location_negative", []):
        locations[p.value] = {"weight": -0.5, "target": False}
    locations = expand_locations(locations)

    seniority: dict[str, dict] = {}
    for p in prefs.get("seniority_wanted", []):
        seniority[p.value] = {"weight": 1.0, "level": p.value}
    for p in prefs.get("seniority_unwanted", []):
        seniority[p.value] = {"weight": -0.5, "level": p.value}

    neg_list = [p.value for p in prefs.get("negative_signal", [])]
    negation_list = [p.value for p in prefs.get("negation_phrase", [])]

    salary_min_str = repo.get_setting("salary_min")
    salary_currency = repo.get_setting("salary_currency", "EUR")

    salary_min: int | None = None
    if salary_min_str:
        try:
            salary_min = int(salary_min_str)
        except ValueError:
            logger.warning("Invalid salary_min setting: %s", salary_min_str)

    return SignalConfig(
        tech_keywords=tech_keywords or None,
        job_titles=job_titles or None,
        locations=locations or None,
        seniority_patterns=seniority or None,
        salary_min=salary_min,
        salary_currency=salary_currency,
        negatives=neg_list or None,
        negation_phrases=negation_list or None,
    )


def _collect_positive_keywords(cfg: SignalConfig) -> list[str]:
    """Gather all positive keyword strings from config for negation check."""
    keywords: list[str] = []
    if cfg.tech_keywords:
        keywords.extend(cfg.tech_keywords)
    if cfg.job_titles:
        keywords.extend(cfg.job_titles)
    if cfg.locations:
        keywords.extend(
            k for k, info in cfg.locations.items() if info["weight"] >= 0
        )
    if cfg.seniority_patterns:
        keywords.extend(
            k for k, info in cfg.seniority_patterns.items() if info["weight"] >= 0
        )
    return keywords


def _filter_dict(
    d: dict[str, dict] | None, suppressed: set[str],
) -> dict[str, dict] | None:
    """Return a copy of *d* with suppressed keys removed.

    Returns None only if *d* was None. If *d* had entries but all were
    suppressed, returns an empty dict so callers don't fall back to defaults.
    """
    if d is None or not suppressed:
        return d
    return {k: v for k, v in d.items() if k.lower() not in suppressed}


def compute_features(
    subject: str, body: str, config: SignalConfig | None = None,
) -> list[float]:
    """Compute the 6 rule-based feature scores as a flat list.

    Used by both RuleBasedScorer and MLTrainer.
    Returns scores in FEATURE_NAMES order.
    """
    text = f"{subject}\n{body}"
    cfg = config or SignalConfig()

    suppressed: set[str] = set()
    if cfg.negation_phrases:
        all_positive = _collect_positive_keywords(cfg)
        suppressed = find_negated_keywords(
            text, cfg.negation_phrases, all_positive,
        )

    tech_kw = _filter_dict(cfg.tech_keywords, suppressed)
    titles = _filter_dict(cfg.job_titles, suppressed)
    locations = _filter_dict(cfg.locations, suppressed)
    seniority = _filter_dict(cfg.seniority_patterns, suppressed)

    return [
        score_tech_stack(text, tech_kw),
        score_job_title(text, titles),
        score_location(text, locations),
        score_seniority(subject, seniority),
        score_salary(text, cfg.salary_patterns, cfg.salary_min),
        score_negatives(text, cfg.negatives, cfg.negation_phrases),
    ]


CONFIDENCE_DIVISOR = 0.4


@dataclass
class ScoringResult:
    score: float
    classification: str
    breakdown: dict[str, float]
    confidence: float = 0.0


class RuleBasedScorer:
    """Computes a score from 0.0 to 1.0 based on extracted signals."""

    def __init__(
        self,
        config: SignalConfig | None = None,
        score_threshold: float | None = None,
    ):
        self.config = config
        self.threshold = (
            score_threshold if score_threshold is not None else settings.score_threshold
        )

    def score(self, subject: str, body: str) -> ScoringResult:
        features = compute_features(subject, body, self.config)
        breakdown = dict(zip(FEATURE_NAMES, features))

        weights = {
            "tech_match": settings.weight_tech_match,
            "job_title": 0.0,  # Incorporated into tech_match weight
            "location_match": settings.weight_location_match,
            "seniority_match": settings.weight_seniority_match,
            "salary_match": settings.weight_salary_match,
            "negative_signals": settings.weight_negative_signals,
        }

        # Boost: if job title matches well, blend it with tech score
        if breakdown["job_title"] > 0:
            breakdown["tech_match"] = max(breakdown["tech_match"], breakdown["job_title"])

        final_score = sum(breakdown[k] * weights[k] for k in breakdown)

        classification = (
            "worth_checking" if final_score >= self.threshold else "skip"
        )

        confidence = min(abs(final_score - self.threshold) / CONFIDENCE_DIVISOR, 1.0)

        return ScoringResult(
            score=round(final_score, 3),
            classification=classification,
            breakdown={k: round(v, 3) for k, v in breakdown.items()},
            confidence=round(confidence, 3),
        )
