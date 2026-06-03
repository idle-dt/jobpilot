# TODO: Web Auth & Sync — Production Readiness

Tasks to implement before the app can support multiple users or run as a hosted web service.

## Critical: Multi-User Support

### 1. Add user model and per-user data scoping
- Create a `users` table (`id`, `email`, `gmail_token` (encrypted), `created_at`)
- Add `user_id` foreign key to `emails`, `scraped_jobs`, `user_feedback` tables
- Scope all repository queries by `user_id` (`WHERE user_id = ?`)
- Store the logged-in user's ID in `session["user_id"]` and `session["user_email"]` after OAuth callback
- Display the logged-in user's email in the nav bar

### 2. Per-user Gmail token storage
- Currently a single `~/.jobpilot/token.json` file is shared — only one Gmail account works at a time
- Move token storage to the database (encrypt at rest) or to per-user files keyed by user ID
- Each user's sync should use their own Gmail credentials

### 3. Fix OAuth state management for concurrent users
- The current file-based approach (`~/.jobpilot/.oauth_pending`) supports only one login flow at a time — a second user starting login overwrites the first user's state
- Store OAuth state + `code_verifier` in the database keyed by the `state` parameter, with an expiration timestamp (e.g., 10 minutes)
- Clean up expired state entries periodically

### 4. Access control on all endpoints
- Add a `@require_login` decorator that checks `session["user_id"]` and returns 401 if missing
- Validate that the logged-in user owns the email/job before allowing feedback (`/api/feedback/*`)
- Scope `/api/sync` to fetch only the current user's Gmail inbox

## High: Security & Infrastructure

### 5. HTTPS and production deployment
- The redirect URI is hardcoded to `http://localhost:5050` — parameterize it via `JOBPILOT_BASE_URL` setting
- Remove `OAUTHLIB_INSECURE_TRANSPORT = "1"` for production; require HTTPS
- Run behind a reverse proxy (nginx/caddy) with TLS termination
- Set `SESSION_COOKIE_SECURE = True`, `SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = "Lax"` in production

### 6. Server-side sessions
- Flask's default signed-cookie sessions can't store much data and are visible to the client
- Switch to server-side sessions (e.g., `flask-session` with Redis or database backend)
- This also fixes the session-not-surviving-redirect issue we worked around with file-based state

### 7. Secret key management
- Currently auto-generated to `~/.jobpilot/.secret_key` — fine for local dev
- For production: require `JOBPILOT_SECRET_KEY` as an environment variable, fail startup if not set
- Rotate keys periodically; support key rotation without invalidating all sessions

### 8. Rate limiting
- Add rate limiting to `/auth/google`, `/auth/callback`, and `/api/sync` to prevent abuse
- Use `flask-limiter` or similar

## Medium: UX & Reliability

### 9. Show logged-in user identity
- Display the authenticated user's email in the nav bar (currently just shows "Logout")
- Extract email from the Gmail token's ID token or make a Gmail API call after login

### 10. Sync progress and history
- Current sync is a blocking HTTP request (5–30 seconds) — works for one user but not at scale
- Move sync to a background task (Celery, RQ, or a simple thread pool)
- Add a `sync_history` table (`id`, `user_id`, `started_at`, `finished_at`, `new_emails`, `status`)
- Show sync history on the settings page
- Use SSE or polling to show real-time sync progress

### 11. Handle token revocation gracefully
- If a user revokes Gmail access, `get_credentials()` will fail on refresh
- Detect `RefreshError`, delete the stale token, and redirect to `/auth/login` with a clear message
- Currently the sync endpoint returns a generic 401

### 12. Multi-account Gmail support
- Allow users to connect multiple Gmail accounts
- Store multiple tokens per user
- Sync fetches from all connected accounts

### 13. Flash message styling
- Flash messages (OAuth errors) currently render but aren't auto-dismissed
- Add JavaScript to auto-dismiss after 5 seconds or add a close button

## Low: Cleanup & Polish

### 14. OAuth state file cleanup
- If a user starts login but never completes it, `~/.jobpilot/.oauth_pending` is never deleted
- Add a TTL check (e.g., delete if older than 10 minutes) — this becomes moot once state moves to the database (task 3)

### 15. CSRF protection on POST endpoints
- `/api/sync` and `/api/feedback/*` accept POST but don't verify a CSRF token
- Add `flask-wtf` CSRF protection or validate the `Origin`/`Referer` header
- htmx sends the correct headers by default, so this mostly needs server-side validation

### 16. Logout should optionally revoke the token
- Currently logout just clears the Flask session — the Gmail token remains on disk
- Add an option to revoke the Google OAuth token on logout (call Google's revoke endpoint)
- At minimum, delete the token file on logout so the user must re-authenticate
