"""Parsing one JSONL line of a labeling run into something the service can act on.

Split from ``label_service.py`` to keep that file under the 300-line limit. The boundary
is real: this module knows the on-disk entry format and nothing about labels, confidence
floors or the Tracker.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from jobpilot.storage.label_repo import LabelEntry

logger = logging.getLogger(__name__)

REASON_MALFORMED = "malformed entry"


@dataclass
class ParsedLine:
    """One input line: either a usable entry or the reason it is not."""

    entry: LabelEntry | None
    reason: str | None
    raw_id: int | None = None


def read_lines(input_path: Path) -> list[str]:
    """Return the non-blank lines of a JSONL file."""
    text = input_path.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def parse_line(line: str) -> ParsedLine:
    """Parse one JSONL entry into a LabelEntry, or explain why it is unusable.

    A malformed line is rejected on its own; it never aborts the run.
    """
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Skipping unparseable label-batch line")
        return ParsedLine(None, REASON_MALFORMED)
    if not isinstance(raw, dict):
        return ParsedLine(None, REASON_MALFORMED)
    job_id, label = raw.get("id"), raw.get("label")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or not isinstance(label, str):
        return ParsedLine(None, REASON_MALFORMED, job_id if isinstance(job_id, int) else None)
    return ParsedLine(
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
