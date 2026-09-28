"""Carrying one verdict to every copy of the same posting.

A run decides a piece of text once — the export shows it once — and this module expands
that decision into one entry per row holding that text, so no copy is left waiting to be
decided again.

The expansion is recomputed here from the grouping rule rather than read back from the
``duplicate_of`` the export emitted. Same principle as the rejection guard in ADR-018: an
agent that ignores its instructions must still produce correct behaviour.

It keys on group *membership*, not on being the representative. A verdict on a piece of
text applies to every copy of that text whichever id happened to name it, and an entry
naming a member would otherwise leave the rest of the group silently unlabeled.
"""

from dataclasses import dataclass, field, replace

from jobpilot.storage.label_repo import REASON_ALREADY_LABELED, LabelEntry


@dataclass(frozen=True)
class FannedOutBatch:
    """One batch of label entries after every duplicate copy has been added to it."""

    entries: list[LabelEntry] = field(default_factory=list)
    """Every entry to write, each input entry immediately followed by its copies."""
    via: dict[int, int] = field(default_factory=dict)
    """{copy id: the job id whose entry it was written on behalf of}."""
    refused: dict[int, str] = field(default_factory=dict)
    """{job id: reason} for input entries a copy of the same text already claimed."""


def siblings_by_id(groups: dict[int, list[int]]) -> dict[int, tuple[int, ...]]:
    """Return {row id: the other ids sharing its text} for every grouped row.

    ``groups`` is keyed by representative; this flips it so any member of a group can
    find the rest in one lookup.
    """
    siblings: dict[int, tuple[int, ...]] = {}
    for representative, members in groups.items():
        group = (representative, *members)
        for job_id in group:
            siblings[job_id] = tuple(other for other in group if other != job_id)
    return siblings


def fan_out(
    entries: list[LabelEntry], siblings: dict[int, tuple[int, ...]],
) -> FannedOutBatch:
    """Expand each entry into one entry per other row holding the same text.

    A copy carries the label, confidence and reason of the entry it came from. The first
    entry to reach a row claims it: a later entry naming a row a copy already covers is
    refused as already labeled rather than silently splitting the group across two
    verdicts. Entries are returned in write order, each followed by its own copies.
    """
    batch = FannedOutBatch()
    claimed: set[int] = set()
    for entry in entries:
        if entry.job_id in batch.via:
            batch.refused[entry.job_id] = REASON_ALREADY_LABELED
            continue
        batch.entries.append(entry)
        claimed.add(entry.job_id)
        for sibling in siblings.get(entry.job_id, ()):
            if sibling in claimed:
                continue
            claimed.add(sibling)
            batch.via[sibling] = entry.job_id
            batch.entries.append(replace(entry, job_id=sibling))
    return batch
