"""Human-readable review document for a bulk labeling run.

A run writes one JSONL line per entry to the audit log, which is the right shape
for a machine and the wrong shape for a person deciding whether to keep 266
labels. This renders the same state as Markdown: what to act on first, then the
rejections grouped so one rule can be judged once instead of row by row.

Groups form by identical reason text rather than by parsing it. Reasons repeat
naturally within a run — "No mobile technology named anywhere in the posting"
covers a hundred rows — so the clusters are exact, and a reason phrased only once
lands in its own short section instead of being mis-bucketed by a keyword guess.
"""

from collections import defaultdict
from pathlib import Path

from jobpilot.storage.label_repo import ASSISTANT_SOURCE, USER_SOURCE
from jobpilot.storage.repository import Repository

DEFAULT_REPORT_PATH = Path("docs/label-queue-result.md")

# Sections in the order a reviewer should read them: what to act on, then what was
# refused, then the queue that is deliberately still undecided.
_LABEL_ORDER = ("worth_checking", "not_a_job", "skip")
_LABEL_HEADINGS = {
    "worth_checking": "Worth checking",
    "not_a_job": "Not a job",
    "skip": "Skip",
}
# Below this a group is one-off judgement rather than a rule worth auditing.
_RULE_GROUP_MIN = 2
_NO_REASON = "No reason recorded"
_SAFE_URL_SCHEMES = ("http://", "https://")
# Markdown structure characters. Escaped in every scraped field, because checking
# the url scheme alone is not enough: a title containing "](javascript:...)" closes
# the intended link and opens one whose scheme was never checked.
_MD_SPECIAL = "\\[]()`*_<>"


def write_label_report(repo: Repository, path: Path = DEFAULT_REPORT_PATH) -> Path:
    """Render the current assistant labels to a Markdown file. Returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_label_report(repo), encoding="utf-8")
    return path


def build_label_report(repo: Repository) -> str:
    """Return the review document for every label currently authored by a bulk run."""
    rows = repo.labels.rows_by_source(ASSISTANT_SOURCE)
    queue = repo.count_scraped_jobs_for_review()
    hand = repo.labels.count_by_source(USER_SOURCE)
    lines = _header(len(rows), queue, hand)
    for label in _LABEL_ORDER:
        subset = [r for r in rows if r["user_label"] == label]
        if subset:
            lines += _label_section(label, subset)
    lines += _unlabeled_section(queue)
    return "\n".join(lines) + "\n"


def _header(total: int, queue: int, hand: int) -> list[str]:
    """Opening block: what this file is and how to undo what it describes."""
    if not total:
        return [
            "# Assistant labels",
            "",
            "No labels are currently authored by a bulk run.",
            f"The review queue holds {queue} jobs.",
        ]
    return [
        f"# Assistant labels — {total} applied",
        "",
        f"Review queue now **{queue}**. Your {hand} hand-clicked labels are untouched,",
        "and none of these train the scoring model unless you turn on",
        "**Train on assistant labels** in Settings → Scoring.",
        "",
        "Disagree with any? Note the id. `jobpilot label-revert --source assistant`",
        "clears **every** assistant label, including ones already approved.",
        "",
        "Rejections are grouped by the reason that decided them, so a rule can be",
        "judged once rather than row by row.",
    ]


def _label_section(label: str, rows: list[dict]) -> list[str]:
    """One label's rows, its repeated reasons grouped and the rest listed singly."""
    lines = ["", f"## {_LABEL_HEADINGS[label]} ({len(rows)})"]
    by_reason = _group_by_reason(rows)

    grouped = {r: v for r, v in by_reason.items() if len(v) >= _RULE_GROUP_MIN}
    singles = [row for r, v in by_reason.items() if len(v) < _RULE_GROUP_MIN for row in v]

    for reason, group in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines += ["", f"### {_escape_md(reason)} ({len(group)})", ""]
        lines += [_entry(row) for row in group]
    if singles:
        lines += ["", f"### Individually judged ({len(singles)})", ""]
        lines += [_entry(row, with_reason=True) for row in sorted(singles, key=lambda r: r["id"])]
    return lines


def _group_by_reason(rows: list[dict]) -> dict[str, list[dict]]:
    """Cluster rows by reason, case-insensitively.

    A run quotes the posting's own wording, so the same rule arrives as both
    "Remote-first" and "remote-first". Folding case keeps one rule in one section;
    the label shown is the spelling that occurred most, so the quote stays real.
    """
    by_key: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_key[(row["label_reason"] or _NO_REASON).casefold()].append(row)
    grouped: dict[str, list[dict]] = {}
    for group in by_key.values():
        spellings = [row["label_reason"] or _NO_REASON for row in group]
        # sorted() before max() so an even split between two spellings resolves the
        # same way every run; set iteration order varies with the hash seed.
        grouped[max(sorted(set(spellings)), key=spellings.count)] = group
    return grouped


def _escape_md(text: str) -> str:
    """Neutralise Markdown structure in a scraped or machine-written field.

    Every field on a job row is untrusted: titles and companies are scraped, and the
    reason is written by a bulk run. Escaping the structure characters keeps them as
    text rather than letting them close a link, open a new one, or start a heading.
    """
    escaped = "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in text)
    return " ".join(escaped.split())


def _entry(row: dict, with_reason: bool = False) -> str:
    """One job as a bullet: id, linked title, company, location, optional reason."""
    title = _escape_md(row["title"] or "(untitled)")
    url = row["url"] or ""
    linked = f"[{title}]({url})" if url.startswith(_SAFE_URL_SCHEMES) else title
    place = _escape_md(row["location"] or "no location")
    line = f"- **{row['id']}** {linked} — {_escape_md(row['company'] or '?')}, {place}"
    if with_reason:
        line += f"  \n  _{_escape_md(row['label_reason'] or _NO_REASON)}_"
    return line


def _unlabeled_section(queue: int) -> list[str]:
    """Explain the remaining queue so its size is not read as a failure."""
    return [
        "",
        f"## Left unlabeled ({queue})",
        "",
        "Still in the review queue. A posting that never states where the work",
        "happens is left for you rather than guessed at — see the silence rule in",
        "`docs/labeling-criteria.md`.",
    ]
