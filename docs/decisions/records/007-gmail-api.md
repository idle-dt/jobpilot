# ADR-007: Gmail API for email access

**Status:** accepted
**Date:** 2026-05-07
**Tags:** integration, email

## Context

JobPilot's core input is the user's own Gmail: job-board digest emails from
LinkedIn, Indeed, Glassdoor, and similar senders. The app needs to read those
messages (headers + HTML/plain bodies) and label processed ones, running locally
on the user's machine against their personal Google account. It must authenticate
as the user (their inbox), not as a service identity.

## Decision

Use the official **Gmail API** via `google-api-python-client`, authenticated with
**OAuth 2.0 InstalledAppFlow** (`google-auth-oauthlib`).

- `auth.py` runs `InstalledAppFlow.from_client_secrets_file(...).run_local_server(port=0)`
  to obtain user consent and persists the resulting token for reuse.
- Requested scopes: `gmail.readonly` and `gmail.modify` (modify is needed to apply
  labels to processed emails).
- `client.py` wraps the API with `build("gmail", "v1", credentials=...)`.
- `fetcher.py` searches monitored sender domains, fetches full message objects, and
  applies labels.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| IMAP | Clunkier auth (app passwords / less-secure-app issues), weaker label/search semantics than the Gmail API. |
| Service account | Cannot access a normal consumer Gmail inbox without domain-wide delegation (Workspace only); wrong fit for a personal account. |
| Email forwarding to a parser | Adds setup friction and a round-trip; loses direct labeling and search. |

## Consequences

### Positive
- First-class access to Gmail search, message bodies, and labels.
- OAuth InstalledAppFlow is the supported path for a locally-run user app.
- Token persists so re-consent is not needed every run.

### Negative / Tradeoffs
- Requires the user to create Google OAuth client credentials and grant consent.
- Tied to Gmail specifically — other mail providers are not supported.

### Risks
- OAuth tokens can expire/revoke and need refresh handling.
- Google API quota and scope-policy changes could affect access.

## Related

- ADRs: [ADR-011](011-digest-parsing.md) (parsing the fetched digest emails)
- Code: `src/jobpilot/gmail/auth.py`, `client.py`, `fetcher.py`
- Commits: `283f9b8` (initial Gmail integration)

> Note: the choice of OAuth InstalledAppFlow over alternatives was not documented in
> code; it is inferred here from the auth implementation and the local single-user model.
