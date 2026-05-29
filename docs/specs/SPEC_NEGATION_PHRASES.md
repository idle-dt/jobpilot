# Spec: Negation-Aware Signal Matching

## Problem

The classifier treats every keyword match as a positive signal, even when the surrounding text negates it. "Remote or hybrid work is not available" currently boosts the location score because "remote" and "hybrid" match as positive location keywords. This leads to false-positive scoring — jobs that explicitly exclude a desirable attribute still get scored as if they offer it.

## Requirements

| # | Requirement | Notes |
|---|-------------|-------|
| 1 | New preference category `negation_phrase` — user can add/remove phrases via Settings UI | Same tag-input UX as other preference categories |
| 2 | Before scoring, scan text for negation phrases | Case-insensitive whole-phrase matching |
| 3 | When a negation phrase matches, suppress any positive keywords found inside it from scoring | Applies across all categories: tech stack, location, job titles, seniority |
| 4 | When a negation phrase matches, record it as a negative signal | Adds to `score_negatives` penalty |
| 5 | Negation phrases appear in `extract_matched_keywords` negative list | So the UI shows why a job was penalized |
| 6 | New "Negation Phrases" section in Settings UI between "Negative Signals" and "Salary Expectation" | Uses the existing `tag_input` macro |
| 7 | Starts empty — no default phrases seeded | User adds their own |

## Implementation Steps

### 1. Register new category in `web/routes.py`

Add `"negation_phrase"` to `ALLOWED_CATEGORIES`. It's a scoring category, so it's already covered by `SCORING_CATEGORIES = ALLOWED_CATEGORIES - {"monitored_domain"}`.

### 2. Update `UserPreference` docstring in `storage/models.py`

Add `'negation_phrase'` to the category list in the docstring.

### 3. Load negation phrases in `rules.py`

Add `negation_phrases: list[str] | None` field to `SignalConfig`.

In `load_signal_config()`, read the new preference type:

```python
negation_phrases = [p.value for p in prefs.get("negation_phrase", [])]
```

Pass to `SignalConfig`.

### 4. Add negation filtering logic in `features.py`

Create a helper function:

```python
def find_negated_keywords(
    text: str,
    negation_phrases: list[str],
    positive_keywords: list[str],
) -> set[str]:
    """Find positive keywords that appear inside matched negation phrases.

    Returns the set of keywords that should be suppressed from positive scoring.
    """
    text_lower = text.lower()
    suppressed: set[str] = set()
    for phrase in negation_phrases:
        if _word_match(phrase, text_lower):
            phrase_lower = phrase.lower()
            for keyword in positive_keywords:
                if keyword.lower() in phrase_lower:
                    suppressed.add(keyword.lower())
    return suppressed
```

### 5. Apply suppression in scoring functions

Modify `compute_features()` in `rules.py` to:

1. Collect all positive keywords from all categories (tech, location, titles, seniority) into a flat list.
2. Call `find_negated_keywords()` with the text, negation phrases, and positive keywords.
3. Build filtered keyword dicts that exclude suppressed keywords.
4. Pass filtered dicts to the individual `score_*` functions.

```python
def compute_features(
    subject: str, body: str, config: SignalConfig | None = None,
) -> list[float]:
    text = f"{subject}\n{body}"
    cfg = config or SignalConfig()

    # Collect all positive keywords for negation check
    all_positive = _collect_positive_keywords(cfg)
    suppressed = set()
    if cfg.negation_phrases:
        suppressed = find_negated_keywords(text, cfg.negation_phrases, all_positive)

    # Build filtered configs excluding suppressed keywords
    tech_kw = _filter_dict(cfg.tech_keywords, suppressed)
    titles = _filter_dict(cfg.job_titles, suppressed)
    locations = _filter_dict(cfg.locations, suppressed)
    seniority = _filter_dict(cfg.seniority_patterns, suppressed)

    return [
        score_tech_stack(text, tech_kw),
        score_job_title(text, titles),
        score_location(text, locations),
        score_seniority(subject, seniority),
        score_salary(text, cfg.salary_patterns, cfg.salary_min),
        score_negatives(text, cfg.negatives, cfg.negation_phrases),
    ]
```

Helper `_collect_positive_keywords` gathers all keys from tech_keywords, job_titles, locations (positive weight only), and seniority_patterns (positive weight only).

Helper `_filter_dict` returns a new dict with suppressed keys removed, or `None` if the result is empty.

### 6. Update `score_negatives` in `features.py`

Add `negation_phrases` parameter. Count matched negation phrases alongside existing negatives:

```python
def score_negatives(
    text: str,
    negatives: list[str] | None = None,
    negation_phrases: list[str] | None = None,
) -> float:
    if not text:
        return 1.0
    if negatives is None:
        from jobpilot.classifier.signals import NEGATIVE_SIGNALS
        negatives = NEGATIVE_SIGNALS
    text_lower = text.lower()

    count = sum(1 for neg in negatives if _word_match(neg, text_lower))
    if negation_phrases:
        count += sum(1 for p in negation_phrases if _word_match(p, text_lower))

    if count == 0:
        return 1.0
    if count == 1:
        return NEGATIVES_ONE_SCORE
    return NEGATIVES_MANY_SCORE
```

### 7. Update `extract_matched_keywords` in `features.py`

Add negation phrase matching. Matched negation phrases go into the `negative` list. Positive keywords that are suppressed by negation phrases should NOT appear in the `positive` list.

```python
# In extract_matched_keywords, after existing logic:

# Negation phrases — add to negatives and suppress overlapping positives
if config.negation_phrases:
    text_lower_full = text_lower  # already defined above
    for phrase in config.negation_phrases:
        if _word_match(phrase, text_lower_full):
            negative.append(phrase)
            # Remove any positive keywords found inside this phrase
            phrase_lower = phrase.lower()
            positive = [kw for kw in positive if kw.lower() not in phrase_lower]
```

### 8. Update `extract_signals` in `signals.py`

Not strictly required since `extract_signals` uses hardcoded lists (not user preferences). But the function should be consistent. Pass negation awareness if a `SignalConfig` is available, or leave unchanged if this function is only used for initial signal extraction before user config is applied.

**Decision needed during implementation:** Check all callers of `extract_signals` — if it's only called during initial ingestion (before scoring), no change needed here. The scoring pipeline uses `compute_features` which we've already updated.

### 9. Add Settings UI section in `templates/settings.html`

Add after the "Negative Signals" `tag_input` call:

```jinja2
{{ tag_input('negation_phrase', 'Negation Phrases', 'e.g., remote is not available…',
   'Phrases that negate a positive keyword — suppresses the match and adds a penalty') }}
```

### 10. Tests

Add tests in a new file `tests/test_negation_phrases.py`:

- Test `find_negated_keywords` with various inputs
- Test `compute_features` with negation suppression
- Test `score_negatives` with negation phrases
- Test `extract_matched_keywords` with negation suppression

## Files to Modify

- `src/jobpilot/web/routes.py` — add `negation_phrase` to `ALLOWED_CATEGORIES`
- `src/jobpilot/storage/models.py` — update `UserPreference` docstring
- `src/jobpilot/classifier/rules.py` — add field to `SignalConfig`, update `load_signal_config`, update `compute_features`
- `src/jobpilot/classifier/features.py` — add `find_negated_keywords`, update `score_negatives`, update `extract_matched_keywords`
- `src/jobpilot/web/templates/settings.html` — add Negation Phrases tag input
- `tests/test_negation_phrases.py` — new test file

## Out of Scope

- NLP-based negation detection (dependency parsing, transformer models)
- Negation in `extract_signals()` (hardcoded signal lists, not user-configurable)
- Default/seeded negation phrases
- Changes to `location_negative`, `seniority_unwanted`, or `negative_signal` categories — they remain as-is

## Verification

### Automated

- `poetry run pytest tests/` — all tests pass
- `poetry run ruff check src/` — no lint errors

### Logic Verification

- [ ] Text "Remote or hybrid work is not available" with negation phrase "remote is not available" configured and "remote" as `location_primary`: `score_location` returns 0.0 (not 0.9), `score_negatives` returns 0.4 (one negative found)
- [ ] Text "Remote or hybrid work is not available" with negation phrase "hybrid is not available" configured and "hybrid" as `location_primary`: `score_location` returns 0.0, hybrid suppressed from positive matches
- [ ] Text "We offer remote work" with negation phrase "remote is not available" configured and "remote" as `location_primary`: `score_location` returns 0.9 (negation phrase not found in text, so no suppression)
- [ ] Text "Remote work available. No visa sponsorship." with negation phrase "remote is not available" and "remote" as `location_primary`, "no visa sponsorship" in `negative_signal`: `score_location` returns 0.9 (phrase not in text), `score_negatives` returns 0.4 (one negative from existing list)
- [ ] `extract_matched_keywords` with negation phrase match: phrase appears in negative list, suppressed keyword does NOT appear in positive list
- [ ] `extract_matched_keywords` without negation phrase match: behavior unchanged, positive keywords appear as normal
- [ ] `find_negated_keywords("no flutter experience needed", ["no flutter experience needed"], ["flutter", "react"])` returns `{"flutter"}` — only "flutter" is suppressed, "react" is unaffected
- [ ] `find_negated_keywords("remote work available", ["remote is not available"], ["remote"])` returns empty set — phrase not in text, nothing suppressed
- [ ] Empty `negation_phrases` list: all scoring functions behave identically to current behavior (no regression)
- [ ] Settings UI: adding "remote is not available" as negation phrase via tag input persists to DB and appears on page reload

### Integration (optional)

- [ ] Add negation phrase "remote is not available" in Settings, sync a job containing that text, verify the job's matched signals show the phrase as negative and "remote" is not in positive signals
- [ ] Score breakdown on job detail page reflects suppressed location score

---

## Implementation Report

> Filled in when the task is complete. Summarize what was done, any deviations from the spec, additional changes not in the original plan, and decisions made during implementation.

**Status:** complete
**Deviations:**
- Spec scenarios 1-2 used text "Remote or hybrid work is not available" with phrase "remote is not available", expecting the phrase to match. However, the phrase is not a contiguous substring of that text (there's "or hybrid work" in between), so `_word_match` correctly returns False. Verification adjusted to use texts containing the exact phrase. This is correct behavior — NLP-based negation detection is explicitly out of scope.
- `_filter_dict` returns empty dict `{}` (not `None`) when all keys are suppressed, preventing score functions from falling back to hardcoded global defaults.
**Additional changes:**
- Fixed outdated `UserPreference` docstring: `'job_title'` → `'job_title_primary', 'job_title_secondary'`.
**Decisions:**
- `extract_signals` in `signals.py` was NOT modified (step 8 in spec). Confirmed it's only called during initial ingestion before user config is applied — the scoring pipeline uses `compute_features` which handles negation.
