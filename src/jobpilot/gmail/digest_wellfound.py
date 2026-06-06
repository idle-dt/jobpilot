"""Wellfound job-alert digest parser."""

import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from jobpilot.gmail.digest_common import _parse_generic_digest

logger = logging.getLogger(__name__)

# Wellfound HTML digest structure. A job card's title is a bold 14px black div.
# The greeting banner (24px, with a background-color) and the "Our take" blurb
# (12px, colored accent) also use font-weight:700, so all three style fragments
# are required to single out a real job title. The company sits in a colored
# span inside the same table cell.
_WELLFOUND_TITLE_STYLE_PARTS = ("font-size: 14px", "font-weight: 700", "color: #000")
_WELLFOUND_COMPANY_COLOR = "#541142"
_WELLFOUND_URL_HOST = "wellfound.com"
# The "Learn more" CTA is a links.wellfound.com redirect pointing at the specific
# job; a card also carries a wellfound.com/company/<slug>/jobs link to the
# company page. Prefer the former and never store the company page.
_WELLFOUND_REDIRECT_HOST = "links.wellfound.com"
_WELLFOUND_COMPANY_PATH = "/company/"
_SAFE_URL_SCHEMES = ("http://", "https://")


def _is_wellfound_title_style(style: str | None) -> bool:
    """Return True if a div's style matches Wellfound's job-title signature."""
    return bool(style) and all(part in style for part in _WELLFOUND_TITLE_STYLE_PARTS)


def _parse_wellfound_digest(html: str, body_text: str) -> list[dict]:
    """Parse a Wellfound job alert digest from HTML.

    Wellfound emails are deeply nested tables; the plain-text body smushes every
    field together, so the generic text parser produces garbage. Each job card is
    a table cell holding a bold title div and a colored company span, with a
    links.wellfound.com redirect in the enclosing table. The primary job is
    rendered twice, so jobs are deduped by (title, company). Falls back to the
    generic text parser when no HTML is available.
    """
    if not html:
        return _parse_generic_digest(body_text)

    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []
    seen: set[tuple[str, str | None]] = set()

    title_divs = soup.find_all("div", style=_is_wellfound_title_style)
    for title_div in title_divs:
        title = title_div.get_text(strip=True)
        cell = title_div.find_parent("td")
        if not title or cell is None:
            continue
        company = _wellfound_company(cell)
        if (title, company) in seen:
            continue
        url = _wellfound_job_url(cell.find_parent("table"))
        if url is None:
            continue
        seen.add((title, company))
        jobs.append({"title": title, "company": company, "url": url})

    # Job-title divs present but nothing extracted means the markup changed
    # (e.g. the link/company structure). Non-job emails have no title divs and
    # legitimately yield zero jobs, so only warn when candidates were found.
    if title_divs and not jobs:
        logger.warning(
            "Wellfound digest: %d job-title div(s) found but no jobs extracted — "
            "email markup may have changed",
            len(title_divs),
        )

    return jobs


def _wellfound_company(cell: Tag) -> str | None:
    """Extract the company name from a Wellfound job card's table cell."""
    span = cell.find("span", style=lambda s: s and _WELLFOUND_COMPANY_COLOR in s)
    return span.get_text(strip=True) if span else None


def _wellfound_job_url(container: Tag | None) -> str | None:
    """Return the best Wellfound job link in a container, or None.

    Prefers the "Learn more" tracking redirect (links.wellfound.com), which
    targets the specific job, over a wellfound.com/company/<slug> page. The href
    comes from untrusted email HTML, so reject non-HTTP schemes (e.g.
    ``javascript:``) and links that don't point at Wellfound.
    """
    if container is None:
        return None
    fallback: str | None = None
    for anchor in container.find_all("a", href=True):
        href = anchor["href"]
        if not href.startswith(_SAFE_URL_SCHEMES):
            continue
        parsed = urlparse(href)
        host = parsed.hostname or ""
        if host == _WELLFOUND_REDIRECT_HOST:
            return href
        is_wellfound = host == _WELLFOUND_URL_HOST or host.endswith(f".{_WELLFOUND_URL_HOST}")
        if is_wellfound and _WELLFOUND_COMPANY_PATH not in parsed.path and fallback is None:
            fallback = href
    return fallback
