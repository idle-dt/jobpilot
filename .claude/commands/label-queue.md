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

Finish at the spot-check gate: point the user at `docs/label-queue-result.md`, tell them
the counts and how many jobs were handed back to them, and do not turn on **Train on
assistant labels** for them.
