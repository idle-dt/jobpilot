Label the unlabeled scraped-job review queue in bulk.

The procedure is in **`docs/labeling-prompt.md`** and the judgments are in
**`docs/labeling-criteria.md`**. Read both in full, then follow the procedure exactly.
Neither is Claude-specific — the same flow runs under any agent — so keep this file a
pointer rather than a second copy that can drift out of step.

Four things that decide whether the run was any good:

1. **Every exported job gets an outcome.** `worth_checking`, `skip`, `not_a_job`, or
   `passed`. Never omit a job — an omission is indistinguishable from one never read.
2. **`passed` is the honest answer below 0.95 confidence**, and it needs a reason. Do not
   inflate confidence to avoid using it.
3. **Coverage must read `all accounted for`.** If it names ids, go back and account for
   them before telling the user you are done.
4. **A "Rules need updating" line is a finding, not a nuisance.** Each id is a job where
   these criteria produced a verdict the user had already cancelled. Report it with your
   reasoning and propose the criteria change that would prevent it. Never work around it
   by emitting a different label you do not believe.

## Two-tier run (Claude Code only)

This section changes only who decides each job. Everything else in the procedure stays
the same. After the export (step 1), count the jobs:

- **Fewer than 30**: decide them yourself, as the procedure describes. A subagent costs
  more than it saves at that size.
- **30 or more**: hand the first pass to the `queue-labeler` subagent (Sonnet). Give it
  the export path and a draft path, both in the scratchpad. Then:
  1. **Do not read the whole export.** Saving that read is the point of the subagent.
     Pull only the jobs you need, by id.
  2. **Re-decide every job it passed.** Read each one and either label it at ≥ 0.95 or
     keep it `passed` with your own reason. Your `passed` is the one that goes to the
     user.
  3. **Spot-check 5 random jobs it labeled**, at least 3 of them decided on a
     description. Title-only labels are the easy ones and prove little. If fewer than 3
     such labels exist, take them all. If you would have decided any of the 5
     differently, do not trust the draft. Review every label in it before applying.
  4. Write the merged JSONL, then continue from step 5 (preview). In the report to the
     user, say how many jobs the subagent decided, how many you re-decided, and what the
     spot-check found.

Write the run record (procedure step 8) before reporting. In a two-tier run, fill its
*First-pass review* section from steps 2–3 above.

Finish at the spot-check gate: point the user at `docs/label-queue-result.md` and the new
`docs/label-runs/` record, tell them
the counts and how many jobs were handed back to them, and do not turn on **Train on
assistant labels** for them.
