"""The audit trail of a bulk run: one JSONL line per row the run touched.

Every run — preview or not — leaves a log, so a bulk run is inspectable before and after
the fact. A row written as a copy of another gets its own line carrying ``via``, so the
trail shows why a row nobody labeled by name ended up with a label.

Kept out of ``label_service.py`` so that file stays under the 300-line limit.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jobpilot.storage.label_repo import LabelEntry

OUTCOME_APPLIED = "applied"
OUTCOME_REJECTED = "rejected"
OUTCOME_PASSED = "passed"

AUDIT_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass
class EntryOutcome:
    """What happened to one entry, for the audit log."""

    outcome: str
    reason: str | None = None
    job_id: int | None = None
    label: str | None = None
    confidence: float | None = None
    via: int | None = None
    """Set on a copy: the job id whose entry this row was written on behalf of."""


def copy_outcome(
    entry: LabelEntry, reasons: dict[int, str], via: dict[int, int],
) -> EntryOutcome:
    """Describe one copy written on another row's behalf."""
    reason = reasons.get(entry.job_id)
    return EntryOutcome(
        outcome=OUTCOME_REJECTED if reason else OUTCOME_APPLIED,
        reason=reason,
        job_id=entry.job_id,
        label=entry.label,
        confidence=entry.confidence,
        via=via[entry.job_id],
    )


def write_log(
    log_dir: Path, prefix: str, outcomes: list[EntryOutcome], dry_run: bool,
) -> Path:
    """Write one JSONL line per outcome and return the log path."""
    log_path = _new_log_path(log_dir, prefix)
    with log_path.open("w", encoding="utf-8") as handle:
        for outcome in outcomes:
            handle.write(json.dumps({
                "id": outcome.job_id,
                "label": outcome.label,
                "confidence": outcome.confidence,
                "outcome": outcome.outcome,
                "reason": outcome.reason,
                "via": outcome.via,
                "dry_run": dry_run,
            }) + "\n")
    return log_path


def _new_log_path(log_dir: Path, prefix: str) -> Path:
    """Return a log path no run has used yet.

    The stamp is second-resolution, so a preview and the apply that follows it can
    collide; each run gets its own file rather than appending to another's.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime(AUDIT_TIMESTAMP_FORMAT)
    log_path = log_dir / f"{prefix}-{stamp}.jsonl"
    attempt = 1
    while log_path.exists():
        log_path = log_dir / f"{prefix}-{stamp}-{attempt}.jsonl"
        attempt += 1
    return log_path
