# ADR-014: Plain-HTTP OAuth permitted on loopback only

**Status:** accepted
**Date:** 2026-09-14
**Tags:** security, integration, config

## Context

JobPilot runs as a local-only app and authenticates to Gmail with the OAuth 2.0
authorization-code flow ([ADR-007](007-gmail-api.md)). Google redirects the browser back to
a redirect URI that this app serves itself — `http://localhost:5050/auth/callback`. There is
no TLS terminator in front of the dev server and no public hostname to obtain a certificate
for, so that URI is plain HTTP.

`oauthlib`, sitting under `google-auth-oauthlib`, refuses to parse *any* OAuth response
whose URL is not `https://`. Its `is_secure_transport()` check is bypassed only by setting
the `OAUTHLIB_INSECURE_TRANSPORT` environment variable. So the app cannot complete a login
at all unless it deliberately opts out of that check.

The question is what should gate the opt-out. An earlier attempt gated it on
`settings.debug`, reasoning that plain HTTP is a "development-only" concession. That broke
login outright: `debug` defaults to `False` and nothing in normal operation sets it, so the
flag was never applied and every callback raised `InsecureTransportError`, surfacing as a
500 (see `~/.jobpilot/jobpilot.log`, and the fix in `0eaf44f`).

That failure exposed the real error: **debug mode and transport safety are unrelated
properties.** Running with `debug=False` does not make the connection any less local, and
running with `debug=True` would not make a public HTTP redirect any safer. Gating on debug
both broke the working case and would have permitted the unsafe one.

## Decision

Gate the opt-out on **the redirect URI's host being a loopback address** — not on debug
mode, not unconditionally.

```python
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

def _allow_insecure_loopback_transport() -> None:
    if urlparse(_build_redirect_uri()).hostname not in _LOOPBACK_HOSTS:
        return
    os.environ[_INSECURE_TRANSPORT_ENV] = "1"
    os.environ[_RELAX_TOKEN_SCOPE_ENV] = "1"
```

This follows **RFC 8252 §8.3** ("Loopback Interface Redirection"), which explicitly permits
native apps to use plain HTTP on the loopback interface: the traffic never leaves the host,
so there is no network segment for an attacker to observe. Google's own installed-app flow
depends on this exemption.

The check is called from `callback()` immediately before the token exchange — the only place
oauthlib enforces it. The authorization leg needs no exemption because its endpoint is
Google's own HTTPS URL.

The same helper sets `OAUTHLIB_RELAX_TOKEN_SCOPE`. Because the app requests
`include_granted_scopes=true`, Google may return a normalized or reordered scope set, and
oauthlib's strict string comparison would raise a bare `Warning` and abort an otherwise
successful exchange. Relaxing it disables only that comparison; token validation is
untouched, and the credentials persisted are whatever Google actually granted.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Gate on `settings.debug` | Unrelated property. Broke login in the default configuration (`debug=False`) while still permitting plain HTTP publicly if debug were ever enabled on a deployed instance. |
| Set `OAUTHLIB_INSECURE_TRANSPORT` unconditionally at import | Works today only because the redirect URI is hardcoded to `localhost`. Silently becomes a real vulnerability the moment `JOBPILOT_BASE_URL` is introduced. Fails open. |
| Terminate TLS locally with a self-signed certificate | Requires generating and trusting a local CA, complicates first-run setup, and browsers still warn. Disproportionate for loopback traffic that cannot be intercepted. |
| Use `InstalledAppFlow.run_local_server()` instead of the web flow | That is what `gmail/auth.py` does for the CLI, but it opens its own ephemeral server and cannot integrate with the app's existing session and login page. It also relies on the same loopback exemption internally. |
| Patch `oauthlib`'s check directly | Monkey-patching a security check in a dependency is far more fragile and less legible than the documented environment variable. |

## Consequences

### Positive
- Login works in the default configuration, with no environment setup.
- The exemption is tied to the property that actually justifies it, so the reasoning is
  legible at the call site rather than folded into an unrelated flag.
- Fails *closed*: introducing a non-loopback `JOBPILOT_BASE_URL` automatically withdraws the
  exemption and requires HTTPS, rather than silently inheriting it.

### Negative / Tradeoffs
- The flag is a process-wide `os.environ` write, and once set it is never unset for the life
  of the process. Harmless while the redirect URI can only be `localhost`, but it means the
  relaxation is not scoped to a single request.
- Writing to `os.environ` from a request handler is a side effect in an otherwise pure
  helper. It is what oauthlib's API requires; there is no per-session override.
- `OAUTHLIB_RELAX_TOKEN_SCOPE` means a genuine scope mismatch will no longer surface as an
  error. The granted scopes are still recorded in `token.json` and can be inspected there.

### Risks
- If `_build_redirect_uri()` is ever made configurable (TODO item #5 in
  `docs/todos/TODO_web_auth_and_sync.md`) without the loopback check being re-verified, a
  public deployment could end up transmitting authorization codes over plain HTTP.
  `tests/test_auth_routes.py::test_non_loopback_redirect_still_requires_https` guards this.
- The loopback host list is a fixed set. An exotic loopback alias (e.g. `127.0.0.2`) would
  not match and would be denied — failing closed, which is the correct direction.

## Related

- ADRs: [ADR-007](007-gmail-api.md) (Gmail API and OAuth scopes),
  [ADR-012](012-pydantic-settings.md) (`server_port` feeds the redirect URI)
- Code: `src/jobpilot/web/auth_routes.py`, `tests/test_auth_routes.py`
- Docs: `docs/todos/TODO_web_auth_and_sync.md` (item 5, HTTPS and production deployment)
- Commits: `0eaf44f` (loopback gate replacing the debug gate),
  `83f7034` (introduced the debug gate that broke login)
- Reference: [RFC 8252 §8.3](https://datatracker.ietf.org/doc/html/rfc8252#section-8.3)
