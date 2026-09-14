Label the unlabeled scraped-job review queue in bulk, against `docs/labeling-criteria.md`.

The queue is too large to clear by hand, and the labels it produces become the scoring
model's training set. So every run is provenance-tagged (`label_source='assistant'`),
reversible in one command, and held out of training until the user opts in. Follow the
steps in order — the gate at the end is the point of the whole exercise.

## 1. Read the criteria

Read `docs/labeling-criteria.md` in full. It is the only source of truth for what each
label means. Do not label from memory of a previous run — the file may have been edited.

## 2. Export the queue

```bash
sqlite3 -json ~/.jobpilot/jobpilot.db \
  "SELECT id, title, company, location, description FROM scraped_jobs
   WHERE user_label IS NULL AND classification != 'skip' ORDER BY id" \
  > /tmp/queue.json
```

Jobs already carrying a label are excluded — a run never overwrites one. Auto-skipped
jobs (`classification='skip'`) are out of scope: labeling them would cement the rule
scorer's own judgments as training truth.

## 3. Classify in two passes

**Pass 1 — titles only.** Walk every row's title and apply the hard disqualifiers from
the criteria doc (junior/intern/entry-level, clearly non-mobile stacks, obvious
non-jobs). A title-only disqualification is cheap and high-confidence. Most of the queue
falls here.

**Pass 2 — descriptions of the survivors.** Read the description for everything pass 1
did not decide. This is where the "is mobile the *main* tech here, or one line in a
full-stack wishlist" judgment gets made. Rows with no description are judged on the
title alone, or left out of the file entirely.

## 4. Write the JSONL

One object per line, in `/tmp/labels.jsonl`:

```json
{"id": 5320, "label": "skip", "confidence": 0.97, "reason": "Hybrid: 2 days WFH, 3 in office"}
```

- `label` is one of `worth_checking`, `skip`, `not_a_job`
- `confidence` is **your own** stated confidence, not a model probability. Anything
  below 0.95 is rejected and the job stays in the queue — that is the correct outcome
  for a judgment you are unsure of, so do not inflate it.
- `reason` is free text, stored on the row and shown in the UI and the review document.
  Write the deciding fact, not a restatement of the label.
- **Reuse the exact same reason string for the same rule.** The review document groups
  rows by identical reason, so one wording means one auditable section and a hundred
  variations mean a hundred rows to read. Do not interpolate the job title or company
  into a reason that applies generally — put per-job specifics in a reason only when
  the deciding fact genuinely differs (a quoted office requirement, say).

Omit a job entirely rather than guessing at it.

## 5. Preview

```bash
PYTHONPATH=src python -m jobpilot label-batch --input /tmp/labels.jsonl --dry-run
```

Nothing is written. Check the counts and read the audit log path it prints — one line
per input entry, each with its outcome and, for rejections, the reason. Investigate any
unexpected `unknown job`, `already labeled`, or `malformed entry` before continuing.

## 6. Apply

```bash
PYTHONPATH=src python -m jobpilot label-batch --input /tmp/labels.jsonl
```

Report the counts to the user, and confirm the review-queue count dropped by exactly the
number applied.

## 7. Write the review document

```bash
PYTHONPATH=src python -m jobpilot label-report
```

Writes `docs/label-queue-result.md` — every applied label, `worth_checking` first, then
rejections grouped by the reason that decided them. It is generated from the database,
so it always matches what is actually stored; do not hand-roll this file. It is
gitignored and meant to be deleted once reviewed. Tell the user the path.

## 8. Spot-check gate — do not skip this

Point the user at `docs/label-queue-result.md` and ask them to confirm or correct.
Auditing by group is the efficient path — accepting one reason accepts every row under
it. Draw their attention to the largest groups and to any rule that rests on inference
rather than on something the posting states.

**Below roughly 95% agreement on any group, revert rather than keep them:**

```bash
PYTHONPATH=src python -m jobpilot label-revert --source assistant
```

Then revise `docs/labeling-criteria.md` with what the disagreements revealed and run
again. Keeping labels that failed the check is the one outcome this whole workflow
exists to prevent — an unaudited imitation of the user's criteria, fitted permanently
into the model.

At or above the bar, tell the user the labels stand, and that they still will not train
the scoring model until they turn on **Train on assistant labels** in Settings →
Scoring. Do not flip that setting for them.
