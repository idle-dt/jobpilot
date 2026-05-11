"""Fetches full job descriptions from job listing URLs."""

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SCRAPE_EXPIRED = "__EXPIRED__"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_TIMEOUT = 15
_MIN_DESCRIPTION_LENGTH = 100


def _is_safe_url(url: str) -> bool:
    """Reject URLs that could cause SSRF (private IPs, non-HTTP schemes)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return False
    except (socket.gaierror, ValueError):
        pass
    return True


class JobPageScraper:
    """Fetches full job descriptions from job listing URLs."""

    def scrape(self, url: str) -> str | None:
        """Fetch and extract the job description text from a URL.

        Returns plain text description, or None if scraping fails.
        """
        if not _is_safe_url(url):
            logger.warning("Blocked unsafe URL: %s", url)
            return None

        try:
            resp = requests.get(
                url, headers=_HEADERS, timeout=_TIMEOUT,
                allow_redirects=False,
            )
            if resp.is_redirect:
                target = resp.headers.get("Location", "")
                if not _is_safe_url(target):
                    logger.warning("Blocked redirect to unsafe URL: %s", target)
                    return None
                if "expired_jd_redirect" in target:
                    logger.info("Detected expired job: %s", url)
                    return SCRAPE_EXPIRED
                resp = requests.get(
                    target, headers=_HEADERS, timeout=_TIMEOUT,
                    allow_redirects=False,
                )
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("Failed to fetch %s", url)
            return None

        html = resp.text
        if "linkedin.com/jobs" in url:
            return self._parse_linkedin(html)
        if "indeed.com" in url:
            return self._parse_indeed(html)
        return self._parse_generic(html)

    def _parse_linkedin(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        desc = soup.find("div", class_="description__text")
        if not desc:
            desc = soup.find("div", class_="show-more-less-html__markup")
        if not desc:
            desc = soup.find("section", class_="description")
        if desc:
            return self._clean_text(desc.get_text(separator="\n"))
        return None

    def _parse_indeed(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        desc = soup.find("div", id="jobDescriptionText")
        if not desc:
            desc = soup.find("div", class_="jobsearch-jobDescriptionText")
        if desc:
            return self._clean_text(desc.get_text(separator="\n"))
        return self._parse_generic(html)

    def _parse_generic(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        # Remove noise elements
        for tag in soup.find_all(["nav", "header", "footer", "script", "style", "aside"]):
            tag.decompose()

        # Try common job description containers
        for selector in [
            {"class_": re.compile(r"job.?description", re.I)},
            {"class_": re.compile(r"description", re.I)},
            {"id": re.compile(r"job.?description", re.I)},
        ]:
            container = soup.find("div", **selector)
            if container:
                text = self._clean_text(container.get_text(separator="\n"))
                if len(text) > _MIN_DESCRIPTION_LENGTH:
                    return text

        # Fallback: main or article content
        main = soup.find("main") or soup.find("article")
        if main:
            text = self._clean_text(main.get_text(separator="\n"))
            if len(text) > _MIN_DESCRIPTION_LENGTH:
                return text

        return None

    @staticmethod
    def _clean_text(text: str) -> str:
        """Collapse excessive blank lines, strip trailing whitespace, remove artifacts."""
        lines = [line.rstrip() for line in text.splitlines()]

        # Collapse runs of 3+ consecutive blank lines down to 2
        collapsed: list[str] = []
        blank_run = 0
        max_consecutive_blanks = 2
        for line in lines:
            if not line.strip():
                blank_run += 1
                if blank_run <= max_consecutive_blanks:
                    collapsed.append(line)
            else:
                blank_run = 0
                collapsed.append(line)

        # Remove "Show more" / "Show less" artifacts
        show_artifact = re.compile(
            r"^[\u2026.]*\s*show\s+more\s*$|^show\s+less\s*$", re.IGNORECASE,
        )
        collapsed = [
            line for line in collapsed
            if not show_artifact.match(line.strip())
        ]

        return "\n".join(collapsed).strip()
