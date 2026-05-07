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


@dataclass
class ScoringResult:
    score: float
    classification: str
    breakdown: dict[str, float]
    confidence: float = 0.0


class RuleBasedScorer:
    """Computes a score from 0.0 to 1.0 based on extracted signals."""

    def score(self, subject: str, body: str) -> ScoringResult:
        text = f"{subject}\n{body}"

        breakdown = {
            "tech_match": score_tech_stack(text),
            "job_title": score_job_title(text),
            "location_match": score_location(text),
            "seniority_match": score_seniority(text),
            "salary_match": score_salary(text),
            "negative_signals": score_negatives(text),
        }

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
