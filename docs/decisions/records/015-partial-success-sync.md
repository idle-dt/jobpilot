# ADR-015: A quota-truncated sync is a success, not a failure

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

Adding retries alone would not have fixed (2) or (3). A quota ceiling is not transient on
the scale of a single request — once the per-minute budget is spent, no amount of in-request
backoff recovers it, and retrying forever inside one sync just moves the failure later.

## Decision

**Treat a quota-exhausted fetch as a truncated-but-complete sync.** The fetch stage returns
what it managed to collect, the remaining five stages run normally, and `last_sync_time` is
written as usual.

Three pieces implement this:

**Retry the genuinely transient part.** `GmailClient._execute` retries on 429/5xx and on 403
with reason `rateLimitExceeded`/`userRateLimitExceeded`, with exponential backoff and
jitter, up to `_MAX_ATTEMPTS`. Other 403s (`insufficientPermissions`), 401 and 404 fail fast
— retrying a permission error only adds latency. `_throttle` additionally paces outbound
calls so the quota is less likely to trip in the first place.

**Truncate rather than raise.** A quota error that survives every retry becomes
`GmailQuotaExhaustedError`, which `fetch_new_emails` catches to `break` the loop and return
`FetchResult(new_emails=N, truncated=True)`. A single message failing for a *non*-quota
reason is skipped instead, so one malformed email cannot abort a 200-message batch.

**Resume on the next run, not by rewinding.** This works because `insert_email` commits per
row and `_process_message` already short-circuits on `repo.get_email(msg_id)`. Rows stored
before the cut-off persist; the next sync re-lists the same query, skips the stored prefix
with local DB lookups costing no quota, and continues into the unprocessed backlog. No
cursor is persisted and no state is needed to make forward progress.

The flag reaches the user as `SyncResult.fetch_truncated` -> `SyncState.truncated` ->
`/api/sync/status` -> "Synced — N new emails — Gmail rate limit reached, run sync again to
continue".

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Retry until the quota window reopens | The per-minute budget needs ~60s to refill. Holding the sync thread that long blocks the UI's progress polling on a condition better resolved by ending the run and starting another. |
| Keep raising, but write `last_sync_time` in a `finally` | Fixes the stale timestamp but not the stranded emails — stages 2-6 still never run, so fetched emails stay unclassified until a later sync happens to succeed. |
| Report it as an error with a friendlier message | Honest about the partial fetch but throws away real work: the emails already stored would remain unprocessed, and "error" is the wrong signal for a run that stored 150 of 200 emails and scored all of them. |
| Persist a pagination cursor across syncs | The `get_email` dedup guard already gives resumption for free. A cursor adds stored state that can desynchronize from the DB, for no gain while the query is bounded at `max_results=200`. |
| Batch requests (`BatchHttpRequest`) | Reduces round trips but not quota cost — Gmail bills per message fetched, which is exactly what exhausts "Total Query Cost". Does not address this failure. |
| Raise the Cloud Console quota | An operational change outside the codebase, and it raises the ceiling without making the app resilient when the higher ceiling is reached. |

## Consequences

### Positive
- A rate-limited run still classifies, parses, scores and scrapes everything fetched so far,
  and still updates "Last Sync".
- Successive syncs make monotonic forward progress through a backlog without refetching.
- The user gets an actionable message ("run sync again") instead of "check server logs".
- Callers never parse `HttpError`: quota exhaustion has its own exception type at the
  `GmailClient` boundary.

### Negative / Tradeoffs
- "Synced" now covers two materially different outcomes. The `truncated` flag distinguishes
  them, but any consumer that ignores the flag will read a partial fetch as a full one.
- Clearing a large backlog may take several manual syncs, with no automatic continuation.
- `_throttle` adds a small fixed delay to every Gmail call, slowing syncs that were never
  near the quota.
- Worst-case a single request now blocks for the sum of its backoffs before giving up,
  where it previously failed immediately.

### Risks
- Truncation is only reported in the UI transiently and in the log. A user who misses the
  message may believe the inbox is fully synced when it is not.
- The retryable-reason set is a fixed allowlist. If Google introduces a new quota reason
  string, it will be classified non-retryable and fail fast — failing closed, which is the
  correct direction, but it would need adding here.
- `_error_reasons` depends on `HttpError.error_details`, populated by
  `google-api-python-client` from `data["error"]["errors"]`. It tolerates the field being a
  plain string, but a future change to that payload shape would silently stop matching
  reasons and turn quota errors into hard failures again.

## Related

- ADRs: [ADR-007](007-gmail-api.md) (Gmail API access and scopes)
- Code: `src/jobpilot/gmail/client.py`, `src/jobpilot/gmail/fetcher.py`,
  `src/jobpilot/services/sync_service.py`, `src/jobpilot/services/sync_state.py`
- Tests: `tests/test_gmail_client.py`, `tests/test_gmail_fetcher.py`
- Reference: [Gmail API usage limits](https://developers.google.com/workspace/gmail/api/reference/quota),
  [Google API error retry guidance](https://developers.google.com/workspace/gmail/api/guides/handle-errors)
