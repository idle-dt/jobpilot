"""Bulk labeling: file parsing, the confidence floor, and the audit trail.

Policy lives here rather than in ``LabelRepository``: the repository decides only
what is writable (does the job exist, is the label in the vocabulary, is it
already labeled), while this service decides what is *trustworthy* enough to
offer it. Every run — preview or not — leaves a JSONL log with one line per input
entry, so a bulk run is inspectable before and after the fact.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jobpilot.storage.label_repo import LabelEntry
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)

REASON_BELOW_THRESHOLD = "below threshold"
REASON_MALFORMED = "malformed entry"

OUTCOME_APPLIED = "applied"
OUTCOME_REJECTED = "rejected"

AUDIT_LOG_PREFIX = "label-batch"
REVERT_LOG_PREFIX = "label-revert"
AUDIT_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass
class EntryOutcome:
    """What happened to one input entry, for the audit log."""

    outcome: str
    reason: str | None = None
    job_id: int | None = None
    label: str | None = None
    confidence: float | None = None


@dataclass
class BatchRun:
    """Summary of one label-batch run."""

    applied: int
    rejected: int
    below_threshold: int
    log_path: Path
    dry_run: bool


@dataclass
class _ParsedLine:
    """One input line: either a usable entry or the reason it is not."""

    entry: LabelEntry | None
    reason: str | None
    raw_id: int | None = None


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
        parsed = [self._screen(line, min_confidence) for line in _read_lines(input_path)]
        to_apply = [p.entry for p in parsed if p.entry and not p.reason]
        result = self.repo.labels.apply_labels(to_apply, force=force, dry_run=dry_run)
        repo_reasons = {r.job_id: r.reason for r in result.rejected}
        outcomes = [self._resolve(p, repo_reasons) for p in parsed]
        log_path = self._write_log(AUDIT_LOG_PREFIX, outcomes, dry_run)
        return BatchRun(
            applied=sum(1 for o in outcomes if o.outcome == OUTCOME_APPLIED),
            rejected=sum(1 for o in outcomes if o.outcome == OUTCOME_REJECTED),
            below_threshold=sum(1 for o in outcomes if o.reason == REASON_BELOW_THRESHOLD),
            log_path=log_path,
            dry_run=dry_run,
        )

    def revert(self, source: str, dry_run: bool = False) -> BatchRun:
        """Clear every label authored by one source, logging the affected ids."""
        job_ids = self.repo.labels.job_ids_by_source(source)
        if not dry_run:
            self.repo.labels.clear_labels_by_source(source)
        outcomes = [
            EntryOutcome(outcome=OUTCOME_APPLIED, job_id=job_id) for job_id in job_ids
        ]
        log_path = self._write_log(REVERT_LOG_PREFIX, outcomes, dry_run)
        return BatchRun(
            applied=len(job_ids), rejected=0, below_threshold=0,
            log_path=log_path, dry_run=dry_run,
        )

    @staticmethod
    def _screen(line: str, min_confidence: float) -> _ParsedLine:
        """Parse one JSONL line and apply the confidence floor to it."""
        parsed = _parse_line(line)
        if parsed.reason or parsed.entry is None:
            return parsed
        if (parsed.entry.confidence or 0.0) < min_confidence:
            return _ParsedLine(parsed.entry, REASON_BELOW_THRESHOLD, parsed.raw_id)
        return parsed

    @staticmethod
    def _resolve(parsed: _ParsedLine, repo_reasons: dict[int, str]) -> EntryOutcome:
        """Turn a screened line plus the repository's verdict into one outcome."""
        entry = parsed.entry
        reason = parsed.reason or (repo_reasons.get(entry.job_id) if entry else None)
        return EntryOutcome(
            outcome=OUTCOME_REJECTED if reason else OUTCOME_APPLIED,
            reason=reason,
            job_id=entry.job_id if entry else parsed.raw_id,
            label=entry.label if entry else None,
            confidence=entry.confidence if entry else None,
        )

    def _write_log(
        self, prefix: str, outcomes: list[EntryOutcome], dry_run: bool,
    ) -> Path:
        """Write one JSONL line per entry and return the log path."""
        log_path = self._new_log_path(prefix)
        with log_path.open("w", encoding="utf-8") as handle:
            for outcome in outcomes:
                handle.write(json.dumps({
                    "id": outcome.job_id,
                    "label": outcome.label,
                    "confidence": outcome.confidence,
                    "outcome": outcome.outcome,
                    "reason": outcome.reason,
                    "dry_run": dry_run,
                }) + "\n")
        return log_path

    def _new_log_path(self, prefix: str) -> Path:
        """Return a log path no run has used yet.

        The stamp is second-resolution, so a preview and the apply that follows it
        can collide; each run gets its own file rather than appending to another's.
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime(AUDIT_TIMESTAMP_FORMAT)
        log_path = self.log_dir / f"{prefix}-{stamp}.jsonl"
        attempt = 1
        while log_path.exists():
            log_path = self.log_dir / f"{prefix}-{stamp}-{attempt}.jsonl"
            attempt += 1
        return log_path


def _read_lines(input_path: Path) -> list[str]:
    """Return the non-blank lines of a JSONL file."""
    text = input_path.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def _parse_line(line: str) -> _ParsedLine:
    """Parse one JSONL entry into a LabelEntry, or explain why it is unusable.

    A malformed line is rejected on its own; it never aborts the run.
    """
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Skipping unparseable label-batch line")
        return _ParsedLine(None, REASON_MALFORMED)
    if not isinstance(raw, dict):
        return _ParsedLine(None, REASON_MALFORMED)
    job_id, label = raw.get("id"), raw.get("label")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or not isinstance(label, str):
        return _ParsedLine(None, REASON_MALFORMED, job_id if isinstance(job_id, int) else None)
    return _ParsedLine(
        LabelEntry(
            job_id=job_id,
            label=label,
            confidence=_as_confidence(raw.get("confidence")),
            reason=raw.get("reason") if isinstance(raw.get("reason"), str) else None,
        ),
        None,
        job_id,
    )


def _as_confidence(value: object) -> float | None:
    """Coerce a stated confidence to a float, or None when it is not a number.

    A missing or unusable confidence stays None and so falls below every floor —
    an unstated confidence is not a high one.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
