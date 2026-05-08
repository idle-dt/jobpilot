"""Rule-based scoring engine for job email classification."""

from dataclasses import dataclass

from jobpilot.classifier.features import (
    score_job_title,
    score_location,
    score_negatives,
    score_salary,
    score_seniority,
    score_tech_stack,
)
from jobpilot.config import settings

FEATURE_NAMES = [
    "tech_match", "job_title", "location_match",
    "seniority_match", "salary_match", "negative_signals",
]


def compute_features(subject: str, body: str) -> list[float]:
    """Compute the 6 rule-based feature scores as a flat list.

    Used by both RuleBasedScorer and MLTrainer.
    Returns scores in FEATURE_NAMES order.
    """
    text = f"{subject}\n{body}"
    return [
        score_tech_stack(text),
        score_job_title(text),
        score_location(text),
        score_seniority(text),
        score_salary(text),
        score_negatives(text),
    ]


@dataclass
class ScoringResult:
    score: float
    classification: str
    breakdown: dict[str, float]
    confidence: float = 0.0


class RuleBasedScorer:
    """Computes a score from 0.0 to 1.0 based on extracted signals."""

    def score(self, subject: str, body: str) -> ScoringResult:
        features = compute_features(subject, body)
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
            "worth_checking" if final_score >= settings.score_threshold else "skip"
        )

        confidence = min(abs(final_score - settings.score_threshold) / 0.4, 1.0)

        return ScoringResult(
            score=round(final_score, 3),
            classification=classification,
            breakdown={k: round(v, 3) for k, v in breakdown.items()},
            confidence=round(confidence, 3),
        )
