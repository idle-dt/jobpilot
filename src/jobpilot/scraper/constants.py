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

# Scrape strategies
STRATEGY_REQUESTS_THEN_BROWSER = "requests_then_browser"
STRATEGY_REQUESTS_ONLY = "requests_only"

# Domains where we attempt to scrape full job descriptions.
# LinkedIn: requests first, browser fallback.
# Glassdoor: requests only (login walls block browser too).
SCRAPABLE_DOMAINS: dict[str, str] = {
    "linkedin.com": STRATEGY_REQUESTS_THEN_BROWSER,
    "glassdoor.com": STRATEGY_REQUESTS_ONLY,
}
