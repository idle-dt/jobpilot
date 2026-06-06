"""Business logic for assembling the settings-page context."""

import logging

from jobpilot.config import settings
from jobpilot.scraper.browser import ALLOWED_SITES
from jobpilot.storage.repository import Repository

logger = logging.getLogger(__name__)


class SettingsService:
    """Assembles the settings-page context: settings, preferences, domains, sessions."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def build_context(self) -> dict:
        """Return the full template context for the settings page."""
        from jobpilot.gmail.fetcher import MONITORED_DOMAINS

        prefs = self.repo.get_all_preferences()
        return {
            "sync_days": self.repo.get_setting("sync_days", "7"),
            "score_threshold": self.repo.get_setting(
                "score_threshold", str(settings.score_threshold)
            ),
            "prefs": prefs,
            "salary_currency": self.repo.get_setting("salary_currency", "EUR"),
            "salary_min": self.repo.get_setting("salary_min", ""),
            "salary_max": self.repo.get_setting("salary_max", ""),
            "arbeitnow_enabled": self.repo.get_setting("arbeitnow_enabled", "false")
            == "true",
            "arbeitnow_visa_only": self.repo.get_setting("arbeitnow_visa_only", "false")
            == "true",
            "domain_list": self._build_domain_list(prefs, MONITORED_DOMAINS),
            "browser_sessions": self._build_browser_sessions(),
        }

    @staticmethod
    def _build_domain_list(prefs: dict, monitored_domains: list[str]) -> list[dict]:
        """Merge known monitored domains with active user preferences (deduped)."""
        active_domains = {p.value for p in prefs.get("monitored_domain", [])}
        all_domains = list(
            dict.fromkeys(list(monitored_domains) + sorted(active_domains))
        )
        return [{"domain": d, "active": d in active_domains} for d in all_domains]

    def _build_browser_sessions(self) -> dict:
        """Return a {site: logged_in} map for each scrapeable site."""
        return {
            site: self.repo.get_setting(f"browser_session_{site}", "") == "1"
            for site in ALLOWED_SITES
        }
