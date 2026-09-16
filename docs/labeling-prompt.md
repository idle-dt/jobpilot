# Labeling run — procedure

The instructions for an agent labeling the JobPilot review queue. Tool-neutral on
purpose: Claude Code, Codex, Cursor or a plain script should all be able to follow it.
Nothing here is specific to one assistant.

The judgments themselves are **not** in this file. They live in
`docs/labeling-criteria.md`, which is the only source of truth for what each label means.
This file covers the procedure around them.

## Why the procedure matters

The labels a run writes become the scoring model's training set, so every run is
provenance-tagged (`label_source='assistant'`), reversible in one command, and held out of
training until the user opts in. Two rules exist because both have already gone wrong:

- **Account for every job.** An omitted job is indistinguishable from one never read. A
  previous version of this workflow told agents to omit anything they could not decide;
  128 jobs accumulated in the queue that way, and nothing could tell which had been
  considered and which had been missed.
- **Never re-apply a label the user cancelled.** A cancel is the strongest signal the
  criteria are wrong. Reaching the same verdict again wastes it.

## 1. Export the queue

```bash
PYTHONPATH=src python -m jobpilot label-export --output /tmp/queue.json
```

A JSON array. Each object carries `id`, `title`, `company`, `location`, `url`,
`description`, and:

- **`rejected_labels`** — labels the user has already cancelled on this job. **You may
  not emit any label listed here.** If your reading of the criteria leads you to one of
  them anyway, that is a finding: say so in your report to the user, because it means
  `docs/labeling-criteria.md` still encodes the mistake. The tool will refuse the entry
  regardless.

Already-labeled jobs, jobs a previous run handed back, and jobs the rule scorer
auto-skipped are all absent. The file is exactly the work awaiting a verdict.

## 2. Read the criteria

Read `docs/labeling-criteria.md` in full, every run. Do not label from memory of a
previous run — the file may have been edited, and a run under stale criteria is worse than
no run.

## 3. Decide every job

Two passes are usually cheapest:

1. **Titles.** Apply the hard disqualifiers. A title-only disqualification is cheap and
   high-confidence, and most of the queue falls here.
2. **Descriptions** of everything pass 1 did not settle.

Every job in the export must end as one of four outcomes:

| Outcome | When |
|---|---|
| `worth_checking` | A role the user would open and read |
| `skip` | A real posting they would not pursue |
| `not_a_job` | Not a job posting at all |
| `passed` | **You are under 0.95 confident.** Hand it back |

A posting that states no work mode is **not** automatically `passed` — see *When the
posting says nothing about work mode* in the criteria. A generic title is `skip`; only a
Flutter/Dart or mobile-lead title is handed back.

`passed` is not a label and is not a judgment about the job — it says your confidence was
too low, and the user will decide it themselves in the Inbox. Use it rather than guessing,
and rather than leaving the job out of the file.

## 4. Write the JSONL

One object per line, in `/tmp/labels.jsonl`:

```json
{"id": 5320, "label": "skip", "confidence": 0.97, "reason": "Hybrid: 2 days WFH, 3 in office"}
{"id": 5453, "label": "passed", "reason": "No description; title alone cannot settle stack"}
```

- `confidence` is **your own** stated confidence, not a model probability. Below 0.95 a
  *label* is refused; do not inflate it. `passed` entries are exempt — a hand-back is the
  uncertainty being declared, so a floor on it would reject the entries it exists to
  capture.
- `reason` is the deciding fact, not a restatement of the label. It is stored on the row
  and shown in the UI. **Mandatory on `passed`**: a reasonless hand-back is an omission
  with extra steps.
- **Reuse the exact same reason string for the same rule.** Reviews group rows by
  identical reason, so one wording means one auditable group and a hundred variations mean
  a hundred rows to read. Put per-job specifics in a reason only when the deciding fact
  genuinely differs — a quoted office requirement, say.

Every `id` in the export must appear exactly once.

## 5. Preview

```bash
PYTHONPATH=src python -m jobpilot label-batch --input /tmp/labels.jsonl --dry-run
```

Nothing is written. Check the counts and read the audit log it names — one line per input
entry with its outcome and, for refusals, the reason.

## 6. Apply

```bash
PYTHONPATH=src python -m jobpilot label-batch --input /tmp/labels.jsonl
```

Read all four output lines:

```
Labels: 92 applied, 41 passed to you, 12 tracked, 0 rejected (0 below threshold)
Coverage: 148 in queue — all accounted for
Rules need updating — produced labels you already cancelled: 3 — 5643, 5670, 6384
Audit log: …
```

- **`tracked`** — how many `worth_checking` jobs became Tracker entries.
- **Coverage** must read `all accounted for`. Any listed id is a job you neither labeled
  nor handed back; go back and account for it, then re-run with just those entries.
- **Rules need updating** — each id is a job where the criteria produced a verdict the
  user had already cancelled. Nothing was written for it. Report these to the user with
  your reasoning and propose the change to `docs/labeling-criteria.md` that would prevent
  it. Do not work around it by emitting a different label you do not believe.

## 7. Report to the user

Point them at the review document:

```bash
PYTHONPATH=src python -m jobpilot label-report
```

Tell them the counts, the path, how many jobs were handed back to them, and any rules
conflicts. Auditing by reason group is the efficient path — accepting one reason accepts
every row under it. Draw their attention to the largest groups and to any rule resting on
inference rather than on something the posting states.

Assistant labels do not train the scoring model until the user turns on **Train on
assistant labels** in Settings → Scoring. Do not flip that setting for them.

## Undoing a run

```bash
PYTHONPATH=src python -m jobpilot label-revert --source assistant   # clears its labels
PYTHONPATH=src python -m jobpilot passed-reset                      # clears its hand-backs
```

Neither touches the other's rows, and neither touches the user's own labels or their
record of cancelled labels. Run `passed-reset` after editing the criteria, so jobs passed
over under the old rules get a fresh look under the new ones.
