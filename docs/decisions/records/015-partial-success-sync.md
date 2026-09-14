# ADR-015: Wait out the Gmail quota; "Synced" means every message handled

**Status:** accepted
**Date:** 2026-09-14
**Tags:** integration, email, reliability

## Context

`SyncService.run()` is a six-stage pipeline: fetch emails from Gmail, classify them, parse
digests into individual jobs, fetch ArbeitNow, score, scrape descriptions. Only the first
stage talks to Gmail; the other five operate on rows already in SQLite.

On 2026-09-14 a sync matched 200 messages and fetched them back-to-back with no pacing.
Gmail returned `HttpError 403 ... "Quota exceeded for quota metric 'Total Query Cost' and
limit 'Units per minute per user'"` (reason `rateLimitExceeded`) partway through. Nothing
caught it, so it propagated out of `fetch_new_emails`, out of `run()`, and into the
background thread's handler, which recorded `sync_error`.

Three things went wrong, and only the first is about retries:

1. `GmailClient` had no backoff at all, though Google documents this error as retryable.
2. The emails stored *before* the error were left unclassified and unscored, because stages
   2-6 never ran — even though none of them need Gmail.
3. `last_sync_time` was never written, so the dashboard's "Last Sync" went stale and the
   user was told to "check server logs" for a condition that resolves itself in sixty
   seconds.

In-request backoff alone cannot fix this. A quota ceiling is not transient on the scale of a
single request: once the per-minute budget is spent, no amount of retrying *within* one
request recovers it.

## Decision

**Wait out the quota window and resume, so a sync handles every matched message.** Three
pieces implement this:

**Retry the genuinely transient part.** `GmailClient._execute` retries on 429/5xx and on 403
with reason `rateLimitExceeded`/`userRateLimitExceeded`, with exponential backoff and
jitter. Other 403s (`insufficientPermissions`), 401 and 404 fail fast — retrying a
permission error only adds latency. `_throttle` paces outbound calls at
`_MIN_REQUEST_INTERVAL_SECONDS`, which spreads a 200-message fetch over at least 20 seconds
and makes tripping the quota unlikely to begin with.

**Pause and resume across the quota window.** When a request is still rate-limited after
every retry, `_execute_or_quota_error` raises `GmailQuotaExhaustedError`.
`_fetch_with_resume` catches it, pauses for `_QUOTA_WINDOW_SECONDS` (the metric is "per
minute", so the budget refills within one), and resumes from the *same* message. The pause
is reported via `on_quota_wait` so the UI shows "Waiting for Gmail quota…" rather than
appearing hung.

**Bound the wait, and never overstate the outcome.** Pausing is capped at
`_MAX_QUOTA_WAITS`, so one sync cannot run indefinitely on a large backlog. If the quota is
*still* exhausted after the cap, the run ends in a distinct terminal state — `partial`, not
`done` — reporting "Partially synced — N of M messages". **`done` means every matched
message was handled, and nothing else.** A status word that sometimes means "all 200
handled" and sometimes "150 of 200, keep going" is not a status word.

Resumption across syncs needs no stored cursor: `insert_email` commits per row and
`_process_message` short-circuits on `repo.get_email(msg_id)` *before* calling the API, so a
later sync re-lists the same query, skips the stored prefix with local DB lookups costing no
quota, and walks straight into the unfetched tail.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Report a truncated fetch as "Synced" with a qualifier | The first version of this change did exactly that, and it was wrong: it gave one word two meanings, so any reader or consumer ignoring the qualifier would treat a partial fetch as complete. |
| Truncate and rely on the user re-running sync | Resumption works (verified: a second pass fetches only the remainder, with zero redundant API calls), but leaving it entirely manual means a backlog clears only as often as someone clicks the button. |
| Pause with no cap, until everything is fetched | "Synced" would always be accurate, but a large backlog could hold the sync thread for an unbounded time with no way to end it early. |
| Keep raising, but write `last_sync_time` in a `finally` | Fixes the stale timestamp but not the stranded emails — stages 2-6 still never run. |
| Persist a pagination cursor across syncs | The `get_email` dedup guard already gives resumption for free. A cursor adds stored state that can desynchronize from the DB, for no gain while the query is bounded at `max_results=200`. |
| Batch requests (`BatchHttpRequest`) | Reduces round trips but not quota cost — Gmail bills per message fetched, which is exactly what exhausts "Total Query Cost". |
| Raise the Cloud Console quota | An operational change outside the codebase; raises the ceiling without making the app resilient when the higher ceiling is reached. |

## Consequences

### Positive
- A sync that hits the quota finishes the job itself instead of handing the user a chore.
- `done` has exactly one meaning, so the dashboard cannot overstate what happened.
- A rate-limited run still classifies, parses, scores and scrapes everything fetched, and
  still updates "Last Sync".
- Callers never parse `HttpError`: quota exhaustion has its own exception type at the
  `GmailClient` boundary.

### Negative / Tradeoffs
- A sync that hits the quota now takes at least a minute longer, and up to
  `_MAX_QUOTA_WAITS` minutes, where it previously failed fast. The pause is visible in the
  UI, but the sync button stays busy throughout.
- The wait blocks the background sync thread and holds its SQLite connection open. Acceptable
  for a single-user local app; it would not be for a multi-tenant one.
- `_throttle` adds a small fixed delay to every Gmail call, slowing syncs that were never
  near the quota.
- `partial` is a third terminal state that every status consumer must now handle; one that
  checks only `done`/`error` will silently ignore it.

### Risks
- `_QUOTA_WINDOW_SECONDS` assumes the "per minute" metric. If the binding limit is ever a
  per-day quota instead, the pauses will not help and the run will simply end `partial`
  after burning the cap — correct, but slower than failing fast.
- The retryable-reason set is a fixed allowlist. A new Google quota reason string would be
  classified non-retryable and fail fast — failing closed, the correct direction, but it
  would need adding here.
- `_error_reasons` depends on `HttpError.error_details`, populated by
  `google-api-python-client` from `data["error"]["errors"]`. It tolerates the field being a
  plain string, but a change to that payload shape would silently stop matching reasons and
  turn quota errors into hard failures again.
- `max_results=200` still caps one run. A backlog larger than that is not reachable in a
  single sync regardless of quota, and `partial` does not distinguish that case.

## Related

- ADRs: [ADR-007](007-gmail-api.md) (Gmail API access and scopes)
- Code: `src/jobpilot/gmail/client.py`, `src/jobpilot/gmail/fetcher.py`,
  `src/jobpilot/services/sync_service.py`, `src/jobpilot/services/sync_state.py`
- Tests: `tests/test_gmail_client.py`, `tests/test_gmail_fetcher.py`
- Design: `DESIGN.md` (Sync Button & Progress — `done` vs `partial` presentation)
- Reference: [Gmail API usage limits](https://developers.google.com/workspace/gmail/api/reference/quota),
  [Google API error retry guidance](https://developers.google.com/workspace/gmail/api/guides/handle-errors)
