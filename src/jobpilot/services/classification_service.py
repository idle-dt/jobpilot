"""Email classification and job scoring business logic."""

import json
import logging

from jobpilot.classifier.job_detector import JobDetector
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)


class ClassificationService:
    """Handles email classification and job scoring."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def classify_unprocessed(self) -> None:
        """Score and classify any emails that haven't been processed yet."""
        from jobpilot.classifier.rules import RuleBasedScorer, load_signal_config

        config = load_signal_config(self.repo)
        threshold_str = self.repo.get_setting("score_threshold")
        threshold = float(threshold_str) if threshold_str else None
        scorer = RuleBasedScorer(config=config, score_threshold=threshold)
        rows = self.repo.get_unprocessed_emails()
        detector = JobDetector()
        # Fetched once: the detector only needs to know whether a digest yielded
        # any jobs, so membership answers it without a COUNT(*) per email.
        digested = self.repo.get_email_ids_with_extracted_jobs()

        for row in rows:
            rule = self._reject_rule(detector, row, digested)
            if rule:
                self.repo.update_email_not_job_related(row["id"], rule)
                continue

            text = row["body_text"] or ""
            result = scorer.score(row["subject"], text)

            ml_score = None
            try:
                from jobpilot.classifier.ml_trainer import MLTrainer
                active_noise = self.repo.get_active_model("noise")
                if active_noise:
                    trainer = MLTrainer(self.repo)
                    preds = trainer.predict_single(
                        "noise", "email", row["id"], row["subject"], text,
                    )
                    for pred_data in preds.values():
                        if pred_data.get("is_active"):
                            ml_score = pred_data.get("probability")
                            break
            except (ValueError, KeyError, RuntimeError, FileNotFoundError):
                logger.exception("ML noise prediction failed for %s", row["id"])

            self.repo.update_email_scores(
                row["id"],
                raw_score=result.score,
                ml_score=ml_score,
                classification=result.classification,
                confidence=result.confidence,
            )

    def _reject_rule(
        self, detector: JobDetector, row: dict, digested: set[str],
    ) -> str | None:
        """Return the non-job rule rejecting this email, or None to keep scoring it.

        Detection lives in JobDetector, so the service asks rather than deciding:
        one rule table covers every sender instead of a LinkedIn-only check here.
        ``digested`` holds the email IDs that produced scraped jobs; extraction
        outranks every rejection rule.
        """
        verdict = detector.classify(
            row["subject"], row["sender"], row["platform"],
            row["body_text"], 1 if row["id"] in digested else 0,
        )
        return None if verdict.is_job else verdict.non_job_rule

    def parse_existing_digests(self) -> None:
        """Parse digest emails that haven't been processed for job extraction yet.

        Also re-parses emails whose extracted jobs have boilerplate titles.
        """
        from jobpilot.gmail.digest import (
            _is_boilerplate_line,
            extract_single_job_url,
            parse_digest,
        )

        already_parsed = self.repo.get_email_ids_with_extracted_jobs()

        reparse_email_ids = set()
        boilerplate_rows = self.repo.get_unlabeled_scraped_jobs()
        for row in boilerplate_rows:
            if row["title"] and _is_boilerplate_line(row["title"]):
                reparse_email_ids.add(row["email_id"])

        for eid in reparse_email_ids:
            self.repo.delete_scraped_jobs_for_email(eid)
            already_parsed.discard(eid)

        emails = self.repo.get_emails_needing_origin_url()

        for email in emails:
            if email.id in already_parsed:
                continue

            extracted_jobs = parse_digest(email)
            any_inserted = False
            first_url = None
            for job in extracted_jobs:
                if first_url is None:
                    first_url = job.url
                if self.repo.insert_scraped_job(job):
                    any_inserted = True

            if not extracted_jobs:
                origin_url = extract_single_job_url(email.body_text or "", email.platform)
                if origin_url:
                    self.repo.update_email_origin_url(email.id, origin_url)
            elif not any_inserted and first_url:
                # All jobs were duplicates — link to first URL to prevent orphan
                self.repo.update_email_origin_url(email.id, first_url)

    def score_pending_jobs(self) -> None:
        """Score scraped jobs that are still pending classification."""
        from jobpilot.classifier.features import extract_matched_keywords
        from jobpilot.classifier.rules import RuleBasedScorer, load_signal_config

        config = load_signal_config(self.repo)
        threshold_str = self.repo.get_setting("score_threshold")
        threshold = float(threshold_str) if threshold_str else None
        scorer = RuleBasedScorer(config=config, score_threshold=threshold)
        rows = self.repo.get_pending_scraped_jobs()

        for row in rows:
            body = (
                f"{row['title']} {row['company'] or ''}"
                f" {row['location'] or ''} {row['description'] or ''}"
            )
            result = scorer.score(row["title"], body)

            ml_score = None
            try:
                from jobpilot.classifier.ml_trainer import MLTrainer
                active_scoring = self.repo.get_active_model("scoring")
                if active_scoring:
                    trainer = MLTrainer(self.repo)
                    preds = trainer.predict_single(
                        "scoring", "scraped_job", str(row["id"]), row["title"], body,
                    )
                    for pred_data in preds.values():
                        if pred_data.get("is_active"):
                            ml_score = pred_data.get("probability")
                            break
            except (ValueError, KeyError, RuntimeError, FileNotFoundError):
                logger.exception("ML scoring prediction failed for job %d", row["id"])

            signals = extract_matched_keywords(body, config, subject=row["title"])
            has_signals = signals["positive"] or signals["negative"]
            signals_json = json.dumps(signals) if has_signals else None

            self.repo.update_scraped_job_scores(
                row["id"], result.score, ml_score, result.classification,
                matched_signals=signals_json,
            )
