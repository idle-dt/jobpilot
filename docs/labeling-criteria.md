# Labeling Criteria

The single source of truth for what each label means. Every `jobpilot label-batch`
run is judged against **this file**, not against a prompt, so that a bulk run is
reproducible and a disagreement is fixable by editing one document.

Edit this by hand. It is deliberately prose, not code: the central judgment —
*is mobile/Flutter the main job here, or a line item on a full-stack wishlist?* —
is semantic and resists a keyword list. The rule scorer in
`src/jobpilot/classifier/signals.py` already does the keyword part; this file
covers what the keywords miss.

> **Starting point, not a transcript.** The first version below was derived from
> what the repository already encodes: `signals.py` weights and the seeded
> defaults (salary floor EUR 60,000, score threshold 0.6). Revise it wherever it
> does not match your actual judgment — especially after the first spot-check.

## The three labels

### `worth_checking`

A role you would genuinely open and read. Concretely: the job is **fully remote**,
the seniority is senior/lead/staff, mobile is the **core** of the work, and nothing
in the hard-disqualifier list below applies.

"Mobile is the core" is deliberately broader than Flutter. All of these qualify:

- Flutter or Dart as the primary stack
- **Native Android** — Kotlin or Java, with no Flutter anywhere in the posting
- A full-stack role where **mobile is the primary tech**, with the backend or web
  work in support of it

Also `worth_checking` when the posting is plausibly a fit but thin — a title that
matches with no description to contradict it. A missing description is not
evidence against a job. When genuinely torn, prefer `worth_checking`: the cost of
reading one extra posting is far lower than the cost of never seeing a good one.

This is how the remote requirement interacts with a thin posting: **silence is not
a disqualifier, and it is not a decision either.** Hybrid and on-site are `skip`
only when the posting *says so* — a stated office requirement, a set number of
office days, an explicit "onsite" on the location line. A city sitting in the
location field is **not** such a statement: most postings name a city regardless of
work mode.

So a posting whose title matches and which never says where the work happens is
**left unlabeled**. Not `skip`, not `worth_checking` — it stays in the queue for
you to decide. Leaving it is the correct outcome: guessing from a city name once
put 10 Android roles into `skip` on no evidence at all, which is the failure this
rule exists to prevent.

### `skip`

A real job posting that you would not pursue. The most common cases:

- Anything not fully remote — on-site or hybrid, wherever it is
- iOS or Swift only, with no Android and no cross-platform work
- Mobile is a minor part of a broadly full-stack or backend role
- Junior, intern, entry-level, or working-student seniority
- A stack with no mobile component at all (pure backend, data, DevOps, QA)

`skip` is a judgment about fit. It is never a fallback for "I could not tell" —
that is what leaving a job unlabeled is for.

### `not_a_job`

Not a job posting at all: newsletters, platform announcements, event invitations,
course and certification ads, recruiter-services pitches, digest wrappers that
carry no individual role. The content, not the sender, decides this.

## Hard disqualifiers

Any one of these makes the answer `skip` on its own, without reading further:

- **Not fully remote** — on-site, hybrid, "2 days a week in the office", "based in
  our \<city\> office". Remote is a requirement, not a preference: hybrid is a
  `skip` however good the rest of the posting is.
- **Seniority below mid** — junior, intern, entry-level, graduate, working student
- **No sponsorship where sponsorship is needed** — "no visa sponsorship",
  "must already have work authorization", "must be located in \<country\>" for a
  country you are not in
- **Geographically restricted beyond your eligibility** — "US only" / "USA only"
- **Security clearance required**
- **Unpaid, equity-only, or volunteer**

Most of these match `NEGATIVE_SIGNALS` and the negative-weight entries in
`SENIORITY_PATTERNS` and `LOCATION_PATTERNS` in `signals.py`. If you add one here,
consider adding it there too — the rule scorer is what stops these reaching the
queue in the first place.

**The remote requirement is only partly enforced by the scorer.** Remote is already
the sole positive location signal in your preferences, and
`WORKPLACE_NEGATIVE_SIGNALS` now scores hybrid wording down — "hybrid work",
"in-office", "hybride", "hybridarbete" and the rest. That catches roughly 117 of the
299 unlabeled jobs that mention hybrid or on-site.

The remainder still arrive at full score, because the phrases are deliberately
specific: a bare "hybrid" would also match "hybrid app", "hybrid mobile" and
"hybrid ranking", and the first two are cross-platform terms that count in a job's
*favour*. Precision was chosen over recall. **So the scorer narrows the problem; it
does not solve it.** For anything phrased unusually — "3 days from the Berlin hub",
"office-first culture" — this document is still the only thing rejecting it, and
reading the posting is still the job.

## Soft preferences

These shift the judgment but do not decide it alone. A posting strong on several
is `worth_checking` even if it misses one.

| Preference | Pulls toward |
|------------|--------------|
| Flutter or Dart as the primary stack | `worth_checking` |
| Native Android — Kotlin or Java, no Flutter needed | `worth_checking` |
| Title is mobile-first (Flutter/Android/mobile engineer, mobile lead) | `worth_checking` |
| Full-stack where mobile is the primary tech | `worth_checking` |
| Senior, lead, staff, or principal | `worth_checking` |
| Stated salary at or above EUR 60,000 | `worth_checking` |
| iOS/Swift only, no Android and no cross-platform | `skip` |
| React Native as the whole job | `skip` |
| Mobile named once in a long full-stack requirement list | `skip` |
| Contract-to-hire, agency body-shopping | `skip` |
| No salary stated | *neutral* — most postings omit it |

## The ambiguous cases, decided

- **"Software Engineer" with mobile in the description.** Read the description.
  If mobile — Flutter or Android — is the team's product, `worth_checking`; if it
  appears in a "nice to have" list, `skip`.
- **Full-stack: primary tech, or a line item?** The deciding question is what you
  would spend the week doing. A posting whose responsibilities lead with the app
  and mention an API in support of it is `worth_checking`; one listing React, Node,
  Postgres, AWS *and* Flutter as equal bullets is `skip`. When the split is
  genuinely even, it is not primary — `skip`.
- **Hybrid is a `skip`.** Not a judgment call, and not offset by anything else in
  the posting. The one distinction worth drawing: a role advertised as remote that
  mentions an optional quarterly team gathering is still remote; a role requiring a
  set number of office days per week or month is hybrid, and out.
- **Engineering-manager and head-of-mobile roles.** `worth_checking` — they are
  in `TARGET_JOB_TITLES` — unless the posting is explicitly non-technical.
- **Agency and staffing-firm postings for a named client role.** Judge the role,
  not the poster.
- **No description at all.** A title that is a clear `skip` on seniority or stack
  needs no remote evidence — label it. Otherwise leave it unlabeled: a bare city in
  the `location` field says nothing about work mode.
- **A description that never mentions work mode.** Leave it unlabeled, however long
  the description is. Absence of the word "remote" in 3,000 words of text is not
  evidence of an office requirement — plenty of remote postings never use it.
- **Perks and platitudes are not work-mode statements.** "A modern office in
  Amsterdam" in a benefits list, "we have 9 offices across Sweden", and "life
  doesn't pause when you walk into the office" are not office requirements. The
  last one is arguably the opposite. Look for a statement about where *this role*
  is performed.
- **Never import facts about a company from outside the posting.** "It's a
  consultancy, so it'll be on-site at a client" is a guess. Judge the text.
- **iOS-only is a negative flag.** Native Android is in; iOS or Swift with no
  Android and no cross-platform is a `skip`. The asymmetry is deliberate — Android
  counts as mobile core, iOS alone does not.

## Confidence

`label-batch` writes nothing below `--min-confidence` (default 0.95), so state
confidence honestly. The floor is the caller's own stated confidence, not a model
probability, and it exists so that uncertainty stays in the queue instead of
turning into training data.

Reserve confidence at or above 0.95 for judgments a hard disqualifier or an
unambiguous title decides. Anything that hinges on reading intent out of a vague
description belongs below the floor — it will be rejected, the job will stay in
the queue, and you can decide it by hand.

## When the criteria change

Editing this file does not touch any label already written. To re-label under new
criteria: `jobpilot label-revert --source assistant`, then run the batch again.
Hand-clicked labels are never affected by a revert.

The one exception is `--force`, which overwrites an existing label *and* takes
ownership of it: a hand-clicked label overwritten by a forced run becomes an
assistant label, and a later revert clears it rather than restoring your click.
Nothing remembers the original. Use `--force` only on labels you are willing to
lose.
