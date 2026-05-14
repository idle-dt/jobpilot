"""Shared constants for scraper modules."""

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MIN_DESCRIPTION_LENGTH = 100

LOGIN_WALL_SIGNALS: list[str] = [
    "Sign in to set job alerts",
    "Forgot password",
    "Join now",
    "Create an account",
    "Log in to continue",
    "Sign in to view",
]

BROWSER_ONLY_DOMAINS: set[str] = {"glassdoor.com", "wellfound.com"}

BROWSER_SKIP_DOMAINS: set[str] = {"wellfound.com", "glassdoor.com"}
