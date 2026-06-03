"""Playwright-based scraper for JS-rendered and login-gated job pages."""

import logging
import random
import time
from pathlib import Path
from urllib.parse import urlparse

from jobpilot.scraper.constants import (
    MIN_DESCRIPTION_LENGTH,
    USER_AGENT,
)
from jobpilot.scraper.job_page import is_login_wall, is_safe_url

try:
    from playwright.sync_api import (
        BrowserContext,
        Page,
        Playwright,
        sync_playwright,
    )
    from playwright.sync_api import (
        Error as PlaywrightError,
    )
    from playwright.sync_api import (
        TimeoutError as PlaywrightTimeout,
    )
except ImportError as exc:
    raise ImportError(
        "Playwright is required for browser scraping. "
        "Install with: poetry add playwright && playwright install chromium"
    ) from exc

logger = logging.getLogger(__name__)

_PROFILE_DIR = Path.home() / ".jobpilot" / "browser-profile"

_LOGIN_URLS: dict[str, str] = {
    "linkedin": "https://www.linkedin.com/login",
    "glassdoor": "https://www.glassdoor.com/",
}

ALLOWED_SITES: set[str] = set(_LOGIN_URLS.keys())

_NAVIGATION_TIMEOUT_MS = 30_000
_LOGIN_NAV_TIMEOUT_MS = 60_000
_MIN_HUMAN_DELAY = 3.0
_MAX_HUMAN_DELAY = 6.0

_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
]

_CLOUDFLARE_TITLE_SIGNALS: tuple[str, ...] = (
    "Just a moment",
    "Checking your browser",
)
_CLOUDFLARE_CONTENT_MARKERS: tuple[str, ...] = (
    "cf-browser-verification",
    "cf-challenge-stage",
    "challenge-platform",
    "__cf_chl_",
)


def _clear_stale_singleton_lock() -> None:
    """Remove Chrome's SingletonLock if a prior Playwright run left it behind."""
    lock_file = _PROFILE_DIR / "SingletonLock"
    if lock_file.exists():
        lock_file.unlink(missing_ok=True)


def _launch_context(pw: Playwright, *, headless: bool) -> BrowserContext:
    """Launch a persistent browser context with shared settings."""
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(_PROFILE_DIR),
        channel="chrome",
        headless=headless,
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        args=_BROWSER_ARGS,
    )


class BrowserScraper:
    """Playwright-based scraper for JS-rendered and login-gated job pages."""

    def __init__(self, headless: bool = True) -> None:
        """Initialize scraper. Browser context is created lazily on first use."""
        self._headless = headless
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    def _ensure_context(self) -> BrowserContext:
        """Launch persistent browser context on first use."""
        if self._context is not None:
            return self._context

        _clear_stale_singleton_lock()
        self._playwright = sync_playwright().start()
        self._context = _launch_context(self._playwright, headless=self._headless)
        return self._context

    def _open_login_page(self, ctx: BrowserContext, site: str) -> Page:
        """Open a new page and navigate to the site's login URL."""
        page = ctx.new_page()
        login_url = _LOGIN_URLS[site]
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=_LOGIN_NAV_TIMEOUT_MS)
            logger.info("[Scrape] browser: opened %s login — waiting for user", site)
        except (PlaywrightTimeout, PlaywrightError) as exc:
            logger.warning(
                "[Scrape] browser: %s — navigation to %s failed (%s); "
                "leaving browser open for manual navigation",
                site, login_url, exc.__class__.__name__,
            )
        return page

    def login(self, site: str) -> None:
        """Open a visible browser window for manual login to a job site."""
        if site not in ALLOWED_SITES:
            raise ValueError(f"Unknown site: {site}. Allowed: {ALLOWED_SITES}")

        _clear_stale_singleton_lock()

        pw: Playwright | None = None
        ctx: BrowserContext | None = None
        try:
            pw = sync_playwright().start()
            ctx = _launch_context(pw, headless=False)
            page = self._open_login_page(ctx, site)
            page.wait_for_event("close", timeout=300_000)
        except PlaywrightTimeout:
            logger.info("[Scrape] browser: login window timed out for %s", site)
        except (PlaywrightError, OSError):
            logger.info("[Scrape] browser: %s login window closed", site)
        finally:
            try:
                if ctx is not None:
                    ctx.close()
            except (PlaywrightError, OSError):
                pass
            if pw is not None:
                pw.stop()

    def scrape(self, url: str) -> str | None:
        """Open URL in browser, wait for content, extract description."""
        if not is_safe_url(url):
            logger.warning("[Scrape] browser: %s — blocked unsafe URL", url)
            return None

        ctx = self._ensure_context()
        page = ctx.new_page()
        try:
            return self._scrape_page(page, url)
        except PlaywrightTimeout:
            logger.warning("[Scrape] browser: %s — page load timeout", url)
            return None
        except (PlaywrightError, OSError):
            logger.exception("[Scrape] browser: %s — error", url)
            return None
        finally:
            page.close()

    def _scrape_page(self, page: Page, url: str) -> str | None:
        """Navigate, extract, and validate description from a page."""
        page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)
        page.wait_for_load_state("load", timeout=_NAVIGATION_TIMEOUT_MS)
        time.sleep(random.uniform(_MIN_HUMAN_DELAY, _MAX_HUMAN_DELAY))

        if self._is_cloudflare_challenge(page):
            logger.warning(
                "[Scrape] browser: %s — Cloudflare challenge detected, skipping", url,
            )
            return None

        hostname = urlparse(url).hostname or ""
        description = self._extract_for_domain(page, hostname)

        if description and is_login_wall(description):
            logger.warning(
                "[Scrape] browser: %s — login wall detected, session may be expired", url,
            )
            return None
        if description:
            logger.info(
                "[Scrape] browser: %s — description extracted (%d chars)", url, len(description),
            )
        else:
            logger.info("[Scrape] browser: %s — no description found after browser render", url)
        return description

    def _extract_for_domain(self, page: Page, hostname: str) -> str | None:
        """Route to site-specific extractor based on hostname."""
        if hostname == "linkedin.com" or hostname.endswith(".linkedin.com"):
            return self._extract_linkedin(page)
        if hostname == "glassdoor.com" or hostname.endswith(".glassdoor.com"):
            return self._extract_glassdoor(page)
        return self._extract_generic(page)

    def _extract_linkedin(self, page: Page) -> str | None:
        """Extract job description from LinkedIn."""
        selectors = [
            "div.description__text",
            "div.show-more-less-html__markup",
            "section.description",
        ]
        return self._try_selectors(page, selectors)

    def _extract_glassdoor(self, page: Page) -> str | None:
        """Extract job description from Glassdoor."""
        selectors = [
            'div[class*="JobDetails_jobDescription"]',
            'div[class*="jobDescriptionContent"]',
            "div.desc",
            'div[class*="description"]',
        ]
        return self._try_selectors(page, selectors)

    def _is_cloudflare_challenge(self, page: Page) -> bool:
        """Return True if the current page looks like a Cloudflare interstitial.

        Title signals are the primary detector. Content markers are narrowly
        scoped to CF-internal CSS classes / cookie names so legitimate job
        descriptions that mention "verify you are human" don't false-positive.
        """
        try:
            title = page.title()
        except PlaywrightError:
            return False
        if any(sig in title for sig in _CLOUDFLARE_TITLE_SIGNALS):
            return True
        try:
            content = page.content()
        except PlaywrightError:
            return False
        return any(marker in content for marker in _CLOUDFLARE_CONTENT_MARKERS)

    def _extract_generic(self, page: Page) -> str | None:
        """Extract job description using generic heuristics."""
        page.evaluate("""
            for (const tag of document.querySelectorAll(
                'nav, header, footer, script, style, aside'
            )) { tag.remove(); }
        """)
        selectors = [
            'div[class*="job-description" i]',
            'div[class*="jobDescription" i]',
            'div[class*="description" i]',
            "main",
            "article",
        ]
        return self._try_selectors(page, selectors)

    def _try_selectors(self, page: Page, selectors: list[str]) -> str | None:
        """Try each selector in order, return first valid text."""
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() > 0:
                text = locator.first.inner_text().strip()
                if len(text) >= MIN_DESCRIPTION_LENGTH:
                    return text
        return None

    def close(self) -> None:
        """Close browser context and stop Playwright."""
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
