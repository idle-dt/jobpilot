# ADR-019: Deciding postings that state no work mode

**Status:** accepted
**Date:** 2026-09-16
**Tags:** [classification, labeling, process]

## Context

`docs/labeling-criteria.md` held that a posting which never states where the work happens
can never be labeled. The reasoning was recorded and sound at the time: guessing from a
city in the `location` field had once put 10 Android roles into `skip` on no evidence at
all, and the file said so explicitly — *"Leaving it is the correct outcome… which is the
failure this rule exists to prevent."*

The cost of that caution turned out to be most of the queue. After a full labeling run
under the contract in [ADR-018](018-hand-back-and-rejection-record.md), **114 of 417 jobs
came back undecided**, and the two largest groups were exactly this rule firing: 68
postings that never state a work mode and 28 with no description at all.

Two facts, both measured, changed the picture.

**The user already decides these, and decides them one way.** Across their 599
hand-clicked labels, postings with no work-mode evidence went `skip` 225 times and
`worth_checking` 13 times. The rule was protecting them from a judgment they were making
themselves, 95% in one direction.

**But the split is not uniform.** Partitioning the same 238 labels by title:

| Title | `skip` | `worth_checking` | |
|---|---|---|---|
| Generic | 207 | 2 | 99.0% |
| Names Flutter/Dart, or an EM / head-of-mobile / mobile-lead role | 18 | 11 | 62% |

A single policy over both halves is wrong whichever way it points. The generic half is
decided at a rate that clears the 0.95 confidence floor; the strong-title half is close
to a coin-flip, and is precisely where guessing would reproduce the original failure.

## Decision

Split the rule by title. With no work-mode evidence:

- **Generic title → `skip`**, on the strength of 207 of 209 agreeing labels.
- **Strong title → `passed`**, handed to the user, because 18/11 is not a judgment the
  criteria can make.

Recorded in `docs/labeling-criteria.md` under *When the posting says nothing about work
mode*, with the measured table inline so a future reader can see what the rule rests on.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Keep handing all of them back | Measured cost: 96 of 114 jobs the user must label by hand, forever, in a direction they choose 95% of the time anyway |
| `skip` everything with no work-mode evidence | Would have mislabeled 13 of 238, concentrated entirely in Flutter and mobile-EM titles — the roles the user most wants to see |
| `worth_checking` everything with no work-mode evidence | Puts ~100 jobs into the Tracker, making it the queue rather than a shortlist, and inverts a 95% signal |
| Train a classifier on the 599 labels and let it decide | The scoring model is the subject of `SPEC_scorer_precision` and currently has no active version. A rule that can be read, argued with and edited in one file is the right instrument at this size |
| Re-scrape the postings to obtain a work-mode statement | Checked: 24 of the 28 description-less jobs already have `scrape_attempted = 1`, mostly Glassdoor blocks. Low yield |

## Consequences

### Positive
- Clears an estimated 93 of the 114 outstanding hand-backs, and stops the largest source
  of queue accumulation.
- The criteria now rest on the user's own measured behaviour rather than on a single
  remembered incident.
- Where the evidence is genuinely ambiguous, the file now says so explicitly and hands
  over, instead of applying one blanket policy.

### Negative / Tradeoffs
- The project accepts an expected ~1% wrong `skip` on the generic half.
- The rule is now two rules, and a reader must check the title class before applying it.
- "Strong title" is a keyword list (Flutter, Dart, engineering manager, head of mobile,
  mobile lead) and will drift as the user's targets change.

### Risks
- **The evidence is revealed preference, not ground truth.** The 207 skips are the user's
  own clicks on the same postings. If they were skimming and skipping by default, the
  rule inherits that habit and will look self-confirming. The strong-title half is where
  that would bite, and it is the half still handed over.
- A wrong `skip` is now *recoverable* — History shows it with a cancel that returns the
  job to the Inbox and bars a run from repeating the verdict — but it is still less
  visible than a job sitting in the queue. Worth revisiting if cancels on skipped jobs
  become common.
- The base rates were measured on one user's corpus at one point in time. They should be
  re-measured before the thresholds are trusted again.

## Related

- ADRs: [ADR-018](018-hand-back-and-rejection-record.md) — the `passed` outcome this rule
  chooses between; [ADR-017](017-label-provenance-and-training-gate.md) — why assistant
  labels stay out of training until the user opts in
- Specs: `docs/specs/SPEC_scorer_precision.md` — the related precision problem in the rule
  scorer, which this does not address
- Code: `docs/labeling-criteria.md`, `docs/labeling-prompt.md`
