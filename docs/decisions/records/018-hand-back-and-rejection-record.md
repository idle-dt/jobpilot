# ADR-018: Hand-backs and the rejection record

**Status:** accepted
**Date:** 2026-09-16
**Tags:** [ml, database, labeling]

## Context

A bulk labeling run had no way to hand work back and no way to be told it was wrong.

Both gaps were measurable. Across every audit log, 722 entries applied and only 4 were
ever refused for low confidence — so the confidence floor was not the bottleneck.
**128 of 148 queued jobs had never been proposed by any run**: read, undecidable, and
silently omitted, exactly as the workflow then instructed ("Omit a job entirely rather
than guessing"). An omission is indistinguishable from a job the run never opened, so the
same rows were re-read every pass and the queue never cleared.

The second gap was worse because it was invisible. Nothing recorded that the user
disagreed with a label. Cancelling cleared the label and nothing else, so the next run
read the job afresh, reached the same conclusion from the same criteria, and wrote the
same wrong label. Disagreement was discarded at the moment it was most informative.

A third constraint arrived with the goal of running this under Codex or any other agent:
whatever stops a run repeating a mistake cannot live only in a prompt.

## Decision

Two separate mechanisms, each doing one thing.

**`scraped_jobs.ai_passed_at` / `ai_passed_reason` — a hand-back.** Written when a run is
under 0.95 confident. The job **stays in the review queue**, visible and unchanged; the
flag only excludes it from future exports so the same undecidable rows are not re-read
every run. It is not a label, never enters `user_label`, and never reaches training data.
A reason is mandatory — a reasonless hand-back is an omission with extra steps. It clears
when the job is labeled, or via `jobpilot passed-reset` after the criteria change.

**`label_rejections` — a cancelled verdict.** Written when the user cancels a label,
recording the job, the label, and the source and reason it carried. `apply_labels` then
refuses any entry whose `(job_id, label)` appears there, with
`REASON_PREVIOUSLY_REJECTED`, and the run reports those under *"Rules need updating"*.

Three properties of the guard are deliberate:

- **It lives in the repository, not the prompt.** An agent that ignores its instructions
  still cannot re-apply a cancelled label.
- **It is per-label, not per-job.** Cancelling `worth_checking` must not block a later
  `skip` on the same posting.
- **It does not apply to a user's own click**, which instead *clears* the rejection.
  Changing your mind is always allowed; the guard exists to stop a run repeating a
  mistake, never to stop the user deciding.

Rejections are append-only and survive `label-revert`: they are the user's decisions, not
the assistant's output.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| A fourth value of `user_label` (`undecided`) | `ml_repo.py` counts `user_label IS NOT NULL` as "labeled", so it would silently inflate the labeled count and muddy the ADR-017 provenance model. A hand-back is also the opposite of a judgment |
| Keep omitting undecidable jobs | The failure being fixed. An omission cannot be told apart from a job never read |
| Hide handed-back jobs in a separate view | Built first, then discarded. It adds a third place to look and implies the job is in a special state; it is ordinary unlabeled work that only the user will now do |
| Feed cancellations to the agent as prompt counter-examples | Depends on prompt compliance, which cannot hold across tools. Kept as a possible addition *on top of* the repository guard, not instead of it |
| Let a cancelled label be re-applied | The user's strongest signal, discarded. A run would repeat the mistake every pass |
| Clear hand-backs automatically when the criteria file changes | Needs a stored fingerprint of the criteria, and a typo fix would silently re-open a hundred jobs. An explicit `passed-reset` is one command and never surprises |

## Consequences

### Positive
- A run now accounts for every job it is given; the coverage line names anything dropped.
- Undecidable jobs are read once, not every run.
- A cancel is evidence that survives, and surfaces as a named rules problem rather than
  being silently re-litigated.
- The contract is enforceable under any agent, which is what makes `label-export` plus
  `docs/labeling-prompt.md` a real tool-neutral interface rather than a convention.

### Negative / Tradeoffs
- Two more columns and a table on an already wide `scraped_jobs`.
- A cancel is now heavier than a clear: it writes a row and can be refused.
- `passed-reset` is a manual step that is easy to forget after editing the criteria; a
  run will simply not reconsider those jobs until it is run.

### Risks
- The rejection record assumes a cancel means "this verdict is wrong". A user cancelling
  for another reason — tidying, or a job that expired — permanently bars that verdict.
  Mitigated by the Inbox's "Undo", which records nothing, and by a hand click clearing
  the rejection.
- `ai_passed_at` is cleared on labeling by two separate write paths
  (`_APPLY_LABEL_SQL` and `update_scraped_job_label`). A third write path added later
  without that clause would let a decided job still count as handed back.

## Related

- ADRs: [ADR-017](017-label-provenance-and-training-gate.md) — label provenance and the
  training gate, which this extends with a non-label outcome
- Specs: `docs/specs/SPEC_labeling_contract.md`
- Code: `storage/label_repo.py`, `storage/rejection_repo.py`, `services/label_service.py`,
  `docs/labeling-prompt.md`
