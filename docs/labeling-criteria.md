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

There is also a fourth outcome, `passed`, which is **not** a label: it says the run was
under 0.95 confident and is handing the job to you. See *Passing a job back* below.

### `worth_checking`

A role you would genuinely open and read. Concretely: the job is **fully remote**,
the seniority is senior/lead/staff, mobile is the **core** of the work, and nothing
in the hard-disqualifier list below applies.

"Mobile is the core" is deliberately broader than Flutter. All of these qualify:

- Flutter or Dart as the primary stack
- **Native Android** — Kotlin or Java, with no Flutter anywhere in the posting
- A full-stack role where **mobile is the primary tech**, with the backend or web
  work in support of it

A missing description is not evidence *against* a job — but it is not evidence for
one either, and this paragraph used to be read both ways. When genuinely torn between
the two labels, with evidence on both sides, prefer `worth_checking`: the cost of
reading one extra posting is far lower than the cost of never seeing a good one. But
absence of evidence is not that kind of tie — a thin posting you cannot settle at 0.95
confidence is `passed`, not a guess in either direction.

This is how the remote requirement interacts with a thin posting: **silence is not
a disqualifier, and it is not a decision either.** Hybrid and on-site are `skip`
only when the posting *says so* — a stated office requirement, a set number of
office days, an explicit "onsite" on the location line. A city sitting in the
location field is **not** such a statement: most postings name a city regardless of
work mode.

A posting that never says where the work happens is decided by **title strength** —
see *When the posting says nothing about work mode* below. A generic title is `skip`; a
Flutter/Dart or mobile-lead title is `passed`, because that is where the user's own
labels genuinely split.

Whichever way it falls, record it as an explicit entry carrying a reason, never by
omitting the job from the file. An omission is indistinguishable from a job the run
never opened, and that ambiguity is what let 128 jobs pile up in the queue.

### `skip`

A real job posting that you would not pursue. The most common cases:

- Anything not fully remote — on-site or hybrid, wherever it is
- iOS or Swift only, with no Android and no cross-platform work
- Mobile is a minor part of a broadly full-stack or backend role
- Junior, intern, entry-level, or working-student seniority
- A stack with no mobile component at all (pure backend, data, DevOps, QA)

`skip` is a judgment about fit. It is never a fallback for "I could not tell" —
that is what `passed` is for.

### `not_a_job`

Not a job posting at all: newsletters, platform announcements, event invitations,
course and certification ads, recruiter-services pitches, digest wrappers that
carry no individual role. The content, not the sender, decides this.

## Passing a job back

Not a label, and not a judgment about the job. `passed` says the run could not reach
0.95 confidence — most often because the posting never states a work mode, or has no
description and a title that is not itself disqualifying.

A passed job **stays in the review queue**, exactly where it was. Nothing hides, nothing
moves; you label it by hand in the Inbox like any other. The only thing the mark changes
is that future runs skip it, so the same undecidable rows are not re-read every time.

It carries a mandatory reason saying what could not be settled. It never enters
`user_label`, is never counted as a label, and never reaches training data. It clears
only when you label the job, or when someone runs `jobpilot passed-reset` after the
criteria change.

Use it for postings these criteria do not settle — never as somewhere to put a judgment
you could have made by reading further.

## Hard disqualifiers

Any one of these makes the answer `skip` on its own, without reading further:

- **Not fully remote** — on-site, hybrid, "2 days a week in the office", "based in
  our \<city\> office". Remote is a requirement, not a preference: hybrid is a
  `skip` however good the rest of the posting is. Note that "work from home" sits on
  *both* sides of this line — a stated split ("2 days Work from Home, 3 days Work
  from Office") disqualifies, while a bare "possibility to work from home" decides
  nothing. See the ambiguous cases below before acting on either.
- **Seniority below mid** — junior, intern, entry-level, graduate, working student
- **Requires physical presence outside Ukraine** — see *Where the work happens*
  below. This replaces the older "no sponsorship" and "US only" clauses, which asked
  about eligibility the file never recorded and so could never be applied.
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
299 unlabeled jobs that mention hybrid or on-site. "Work from home" no longer counts
as a remote *positive* either: it was removed from `REMOTE_SYNONYMS` in
`classifier/geo.py`, because in 32 postings where it was the only remote evidence,
every single one was in fact not remote.

The remainder still arrive at full score, because the phrases are deliberately
specific: a bare "hybrid" would also match "hybrid app", "hybrid mobile" and
"hybrid ranking", and the first two are cross-platform terms that count in a job's
*favour*. Precision was chosen over recall. **So the scorer narrows the problem; it
does not solve it.** For anything phrased unusually — "3 days from the Berlin hub",
"office-first culture" — this document is still the only thing rejecting it, and
reading the posting is still the job.

## Where the work happens

**You are located in Ukraine, and you can work for a company anywhere.** The company's
own country is therefore *never* a disqualifier on its own. A US, Portuguese or
Australian company hiring fully remote with no location requirement is exactly as
eligible as a Ukrainian one, and a US address in the `location` field says nothing by
itself.

What you cannot do is **be physically somewhere that is not Ukraine**. So a posting is
`skip` when it requires presence elsewhere, however it phrases it:

- On-site or hybrid at an office in any country but Ukraine — "hybrid opportunity for
  candidates from our Seattle, San Francisco, or Detroit offices"
- A stated residency requirement — "You are based in the United States", "must be
  located in \<country\>", "US only" / "USA only"
- Remote, but fenced to one country — "100% Remote - Portugal", "Remote Eligible in
  Bulgaria". Remote that names a country you are not in is still a presence requirement

And it is **not** `skip` merely because:

- The company, its HQ or its other offices are abroad — "Based in Portugal, Wire IT is
  your specialized IT consulting partner" describes the *company*, not the candidate
- Pay is quoted in a foreign currency, or varies by the employee's location
- The `location` field names a foreign city while the body states remote with no
  residency requirement

When a posting states remote and names no country the candidate must live in, treat the
work mode as settled and judge it on stack and seniority like any other. When it states
remote *and* fences it to a country, that is a decision, not an ambiguity — `skip`.

## When the posting says nothing about work mode

The rule below replaces an earlier one. This file used to say that a posting which never
states a work mode is always handed back, on the reasoning that guessing from a city name
once put 10 Android roles into `skip` on no evidence at all. That caution was measured
against the user's own 599 hand-clicked labels and found to be costing far more than it
saved — **but only for part of the queue**, which is why the rule splits.

Of the postings with **no work-mode evidence** — either no description at all, or a
description that never says remote, hybrid, on-site or a number of office days:

| Title | The user chose `skip` | chose `worth_checking` | |
|---|---|---|---|
| **Generic** | 207 | 2 | **99.0% skip** |
| **Strong** | 18 | 11 | 62% — a real coin-flip |

So:

- **Generic title, no work-mode evidence → `skip`.** At 207 of 209 this clears the 0.95
  floor comfortably. "Senior Software Engineer", "Full Stack Software Engineer", "Staff
  Engineer", "Software Engineer II" with nothing else to go on are not roles the user
  pursues, and 128 of them accumulating in the queue helped nobody.
- **Strong title, no work-mode evidence → `passed`.** A title naming **Flutter or Dart**,
  or an **engineering-manager / head-of-mobile / mobile-lead** role, is where the user
  genuinely splits. Guessing here is exactly the failure the old rule existed to prevent,
  so these still go to them.

Two things make the `skip` half safe now that were not true when the old rule was
written. A wrong `skip` is **recoverable**: it appears in History with a cancel button,
and cancelling returns the job to the Inbox *and* bars a run from repeating it. And the
rule **refuses to guess where guessing is actually hard**, rather than applying one
policy to both halves.

The honest caveat: those 207 skips are the user's own clicks on the same evidence, so
this is revealed preference, not ground truth. If they were skimming and skipping by
default, the rule inherits that habit. The strong-title half is where it would matter,
and that half still comes to them.

**This rule needs work-mode evidence to be genuinely absent.** A posting that *does* state
its work mode is decided by *Where the work happens* above, whatever its title. And
"Remote Config", "remote access", "hybrid applications" and "a hybrid role combining
hands-on development and product work" are **not** work-mode statements — see the
ambiguous cases below.

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
  needs no remote evidence — label it. Otherwise decide it by title under *When the
  posting says nothing about work mode*: a bare city in the `location` field says
  nothing about work mode either way.
- **A description that never mentions work mode.** Absence of the word "remote" in
  3,000 words of text is not evidence of an office requirement — plenty of remote
  postings never use it. Decide it by title under *When the posting says nothing about
  work mode*: generic title `skip`, strong title `passed`.
- **Perks and platitudes are not work-mode statements.** "A modern office in
  Amsterdam" in a benefits list, "we have 9 offices across Sweden", and "life
  doesn't pause when you walk into the office" are not office requirements. The
  last one is arguably the opposite. Look for a statement about where *this role*
  is performed.
- **"The possibility to work from home" is not a remote policy — and not a
  disqualifier either. These are `passed`.** The phrase presupposes a default
  workplace that is not your home, so it leans *against* fully remote; a
  remote-first company writes "remote-first" or "work from anywhere". But it never
  says how much time the office actually claims, and that is the fact the decision
  turns on. Across 1,668 scraped postings this phrasing — "possibility to", "option
  to", "ability to", "some" work from home — appeared 10 times and **not one of
  those roles was remote**. So it is a real signal, just not one that clears the
  confidence floor by itself.

  Do not confuse it with a **stated split**, which contains the same words and *is*
  a hard disqualifier: "Hybrid: 2 days Work from Home, 3 days Work from Office".
  37 postings state a split like that, and none of them is remote either. The
  question to ask is whether the posting commits to office time. If it names days,
  decide it `skip`; if it only dangles the possibility, `passed`.
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
description belongs below the floor — say `passed` and hand it over, rather than
stating a confidence you do not have.

The floor does not apply to `passed` itself, which is the uncertainty being declared
rather than a judgment being offered. State a reason instead; a hand-back without one
is refused.

## When the criteria change

Editing this file does not touch any label already written, and it does not clear a
hand-back either. To re-label under new criteria:
`jobpilot label-revert --source assistant`, then run the batch again. To give the jobs a
previous run passed over a fresh look: `jobpilot passed-reset`. Neither command touches
the other's rows, and hand-clicked labels are never affected by either.

Neither clears your **cancelled labels**. When you cancel a label, that verdict is
recorded permanently and no run may reach it again on that job — a run that does is told
to stop and report the conflict, because it means these criteria still encode the
mistake. Only applying that label by hand clears the record, since that is you changing
your mind.

The one exception is `--force`, which overwrites an existing label *and* takes
ownership of it: a hand-clicked label overwritten by a forced run becomes an
assistant label, and a later revert clears it rather than restoring your click.
Nothing remembers the original. Use `--force` only on labels you are willing to
lose.
