"""Bulk labeling: file parsing, the confidence floor, and the audit trail.

Policy lives here rather than in ``LabelRepository``: the repository decides only
what is writable (does the job exist, is the label in the vocabulary, is it
already labeled), while this service decides what is *trustworthy* enough to
offer it. Every run — preview or not — leaves a JSONL log through ``label_audit``,
with one line per row it touched, so a bulk run is inspectable before and after
the fact. A verdict reaches every copy of the same posting via ``label_fanout``.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from jobpilot.services.label_audit import (
    OUTCOME_APPLIED,
    OUTCOME_PASSED,
    OUTCOME_REJECTED,
    EntryOutcome,
    copy_outcome,
    write_log,
)
from jobpilot.services.label_fanout import fan_out, siblings_by_id
from jobpilot.services.label_parsing import (
    ParsedLine,
    parse_line,
    read_lines,
)
from jobpilot.storage.label_repo import (
    PASSED,
    REASON_PREVIOUSLY_REJECTED,
    LabelEntry,
)
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

REASON_BELOW_THRESHOLD = "below threshold"

AUDIT_LOG_PREFIX = "label-batch"
REVERT_LOG_PREFIX = "label-revert"
PASSED_RESET_LOG_PREFIX = "passed-reset"
WORTH_CHECKING = "worth_checking"
# Ids are listed in full up to this many, then summarised. The point is to make a gap
# actionable, not to print a thousand numbers.
MAX_LISTED_IDS = 25


@dataclass
class BatchRun:
    """Summary of one label-batch run.

    The three list fields are the run's honesty report. ``unaccounted`` holds queue ids
    the input mentioned not at all — dropped silently. ``conflicts`` holds entries that
    reached a verdict the user had cancelled, which is evidence the criteria are wrong
    rather than evidence the run misbehaved.

    ``applied`` counts entries; ``covered`` counts the further rows those entries reached
    as copies of the same posting. A run can apply 70 entries and cover 168 rows.
    """

    applied: int
    rejected: int
    below_threshold: int
    log_path: Path
    dry_run: bool
    covered: int = 0
    members_refused: int = 0
    passed: int = 0
    queue_size: int = 0
    unaccounted: list[int] = field(default_factory=list)
    conflicts: list[int] = field(default_factory=list)
    tracked: int = 0


def _count(outcomes: list[EntryOutcome], outcome: str) -> int:
    """Count the entries that ended in one outcome."""
    return sum(1 for o in outcomes if o.outcome == outcome)


def _tally(outcomes: list[EntryOutcome], copies: list[EntryOutcome]) -> dict[str, int]:
    """Count the run's entry outcomes and the rows its copies reached."""
    return {
        "applied": _count(outcomes, OUTCOME_APPLIED),
        "rejected": _count(outcomes, OUTCOME_REJECTED),
        "passed": _count(outcomes, OUTCOME_PASSED),
        "below_threshold": sum(1 for o in outcomes if o.reason == REASON_BELOW_THRESHOLD),
        "covered": _count(copies, OUTCOME_APPLIED),
        "members_refused": _count(copies, OUTCOME_REJECTED),
    }


def _accounted(parsed: list["ParsedLine"], copies: list[EntryOutcome]) -> set[int]:
    """Return the queue ids this run reached — named in the input or as a copy."""
    named = {p.raw_id for p in parsed if p.raw_id is not None}
    return named | {o.job_id for o in copies if o.job_id is not None}


def _ids_refused_as(outcomes: list[EntryOutcome], reason: str) -> list[int]:
    """Return the job ids refused for one reason, in id order."""
    return sorted(
        o.job_id for o in outcomes if o.reason == reason and o.job_id is not None
    )


class LabelBatchService:
    """Applies and reverts bulk labels, enforcing the confidence floor."""

    def __init__(self, repo: Repository, log_dir: Path):
        self.repo = repo
        self.log_dir = log_dir

    def run_batch(
        self,
        input_path: Path,
        min_confidence: float,
        dry_run: bool = False,
        force: bool = False,
    ) -> BatchRun:
        """Apply a JSONL file of labels, writing an audit log either way.

        Entries below ``min_confidence`` are rejected before reaching the
        repository — a rejection writes nothing and leaves the job in the queue.
        """
        parsed = [self._screen(line, min_confidence) for line in read_lines(input_path)]
        queue_ids = self.repo.review_queue_ids()
        repo_reasons, applied_labels, copies = self._apply(parsed, force, dry_run)
        outcomes = [self._resolve(p, repo_reasons) for p in parsed]
        log_path = write_log(self.log_dir, AUDIT_LOG_PREFIX, outcomes + copies, dry_run)
        return BatchRun(
            **_tally(outcomes, copies),
            queue_size=len(queue_ids),
            unaccounted=sorted(set(queue_ids) - _accounted(parsed, copies)),
            conflicts=_ids_refused_as(outcomes + copies, REASON_PREVIOUSLY_REJECTED),
            tracked=self._track(applied_labels, dry_run),
            log_path=log_path,
            dry_run=dry_run,
        )

    def _apply(
        self, parsed: list["ParsedLine"], force: bool, dry_run: bool,
    ) -> tuple[dict[int, str], list[LabelEntry], list[EntryOutcome]]:
        """Route screened entries to labels or hand-backs, fanning duplicates out.

        Returns the refusals keyed by job id, the labels the repository accepted — the
        latter so ``_track`` can mirror worth_checking into the Tracker — and one outcome
        per copy written on another row's behalf. Labels and hand-backs go to different
        calls because they write different columns and refuse on different grounds: a
        hand-back has no ``force`` and must never override a judgment. Copies ride along
        with the entries they came from, so a group is written in one transaction and
        each copy is still checked on its own.
        """
        usable = [p.entry for p in parsed if p.entry and not p.reason]
        passes = [e for e in usable if e.label == PASSED]
        batch = fan_out(
            [e for e in usable if e.label != PASSED],
            siblings_by_id(self.repo.duplicate_groups()),
        )
        label_result = self.repo.labels.apply_labels(
            batch.entries, force=force, dry_run=dry_run,
        )
        pass_result = self.repo.labels.mark_passed(passes, dry_run=dry_run)
        refused = label_result.rejected + pass_result.rejected
        reasons = {r.job_id: r.reason for r in refused if r.job_id is not None}
        copies = [
            copy_outcome(e, reasons, batch.via)
            for e in batch.entries if e.job_id in batch.via
        ]
        return reasons | batch.refused, label_result.applied, copies

    def _track(self, applied: list[LabelEntry], dry_run: bool) -> int:
        """Mirror every applied worth_checking into the Tracker. Returns how many.

        This is what a UI click has always done; doing it here closes the gap where a
        bulk label produced no Tracker entry at all. ``auto_track_scraped_job`` is
        idempotent, so a re-run adds nothing.
        """
        from jobpilot.services.tracker_service import TrackerService

        if dry_run:
            return sum(1 for e in applied if e.label == WORTH_CHECKING)
        tracker = TrackerService(self.repo)
        tracked = 0
        for entry in applied:
            if entry.label != WORTH_CHECKING:
                continue
            if tracker.auto_track_scraped_job(entry.job_id):
                tracked += 1
        return tracked

    def revert(self, source: str, dry_run: bool = False) -> BatchRun:
        """Clear every label authored by one source, logging the affected ids."""
        job_ids = self.repo.labels.job_ids_by_source(source)
        if not dry_run:
            self.repo.labels.clear_labels_by_source(source)
        outcomes = [
            EntryOutcome(outcome=OUTCOME_APPLIED, job_id=job_id) for job_id in job_ids
        ]
        log_path = write_log(self.log_dir, REVERT_LOG_PREFIX, outcomes, dry_run)
        return BatchRun(
            applied=len(job_ids), rejected=0, below_threshold=0,
            log_path=log_path, dry_run=dry_run,
        )

    def reset_passed(self, dry_run: bool = False) -> BatchRun:
        """Clear every hand-back so the next run reconsiders those jobs.

        Used after the criteria are rewritten: the jobs a run passed on were passed under
        the old rules, and new rules deserve a fresh look. Never fires on its own.
        """
        passed_ids = self.repo.passed_job_ids()
        if not dry_run:
            self.repo.labels.clear_passed()
        outcomes = [
            EntryOutcome(outcome=OUTCOME_APPLIED, job_id=job_id) for job_id in passed_ids
        ]
        log_path = write_log(self.log_dir, PASSED_RESET_LOG_PREFIX, outcomes, dry_run)
        # queue_size is left at 0 so no coverage line prints: a reset accounts for
        # nothing, and "all accounted for" would be a false claim about the queue.
        return BatchRun(
            applied=len(passed_ids), rejected=0, below_threshold=0,
            log_path=log_path, dry_run=dry_run,
        )

    @staticmethod
    def _screen(line: str, min_confidence: float) -> ParsedLine:
        """Parse one JSONL line and apply the confidence floor to it.

        Hand-backs are exempt from the floor. The floor exists to keep uncertainty out of
        the labels, and a hand-back *is* the uncertainty being declared — holding it to a
        confidence bar would reject the very entries it exists to capture.
        """
        parsed = parse_line(line)
        if parsed.reason or parsed.entry is None:
            return parsed
        if parsed.entry.label == PASSED:
            return parsed
        if (parsed.entry.confidence or 0.0) < min_confidence:
            return ParsedLine(parsed.entry, REASON_BELOW_THRESHOLD, parsed.raw_id)
        return parsed

    @staticmethod
    def _resolve(parsed: ParsedLine, repo_reasons: dict[int, str]) -> EntryOutcome:
        """Turn a screened line plus the repository's verdict into one outcome."""
        entry = parsed.entry
        reason = parsed.reason or (repo_reasons.get(entry.job_id) if entry else None)
        if reason:
            outcome = OUTCOME_REJECTED
        elif entry and entry.label == PASSED:
            outcome = OUTCOME_PASSED
        else:
            outcome = OUTCOME_APPLIED
        return EntryOutcome(
            outcome=outcome,
            reason=reason,
            job_id=entry.job_id if entry else parsed.raw_id,
            label=entry.label if entry else None,
            confidence=entry.confidence if entry else None,
        )
