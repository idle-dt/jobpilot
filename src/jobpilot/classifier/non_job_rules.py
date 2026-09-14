"""Subject patterns that identify mail which is not a job posting or job alert.

A rule here says "this is account, billing or promotional mail" — it does not say
the job is bad. A genuine job ad the user would skip is still job-related; see the
User-Facing Vocabulary table in SPEC_non_job_email_detection.md.

Every pattern is matched against the raw subject with `re.IGNORECASE`, so patterns
must not assume ASCII: a Gmail storage warning arrives in the account's own
language and has to match just as a English one does.
"""

import re
from dataclasses import dataclass

# Rule names are persisted in emails.non_job_rule, so renaming one orphans the
# history it explains. Add a rule rather than repurposing an existing name.
LINKEDIN_SOCIAL = "linkedin_social"
ACCOUNT_SECURITY = "account_security"
ACCOUNT_STORAGE = "account_storage"
SERVICE_NOTICE = "service_notice"
BILLING_NOTICE = "billing_notice"
PLATFORM_ONBOARDING = "platform_onboarding"
SUBSCRIPTION_CHANGE = "subscription_change"
ALERT_ACTIVATION = "alert_activation"


@dataclass(frozen=True)
class NonJobRule:
    """One named set of subject patterns, optionally scoped to a platform."""

    name: str
    patterns: tuple[re.Pattern[str], ...]
    platforms: frozenset[str] | None = None

    def matches(self, subject: str, platform: str | None) -> bool:
        """Return True if this rule applies to the platform and matches the subject."""
        if self.platforms is not None and platform not in self.platforms:
            return False
        return any(pattern.search(subject) for pattern in self.patterns)


def _compile(*sources: str) -> tuple[re.Pattern[str], ...]:
    """Compile subject patterns case-insensitively."""
    return tuple(re.compile(source, re.IGNORECASE) for source in sources)


# Social-graph noise: connections, profile views, reactions. Scoped to LinkedIn
# because "viewed your profile" is a recruiter signal only there; elsewhere the
# same words appear inside genuine job digests.
_LINKEDIN_SOCIAL = NonJobRule(
    name=LINKEDIN_SOCIAL,
    platforms=frozenset({"linkedin"}),
    patterns=_compile(
        r"wants? to connect",
        r"accepted your invitation",
        r"\bnew invitations?\b",
        r"congratulat",
        r"endorsed you",
        r"viewed your profile",
        r"looked at your profile",
        r"new message from",
        r"sent you a message",
        r"is celebrating",
        r"post impressions",
        r"profile is popular",
        r"search appearances",
        r"you appeared in \d+ search",
        r"your profile photo was changed",
    ),
)

# Account and security mail. "Оповещение системы безопасности" is Google's Russian
# security alert — seven of them sit in the corpus flagged as job opportunities.
_ACCOUNT_SECURITY = NonJobRule(
    name=ACCOUNT_SECURITY,
    patterns=_compile(
        r"security alert",
        r"оповещение системы безопасности",
        r"\bverify your (e-?mail|account|identity)",
        r"\bconfirm your (e-?mail|account)",
        r"(reset|change) your password",
        r"password (reset|changed)",
        r"two-factor|2-step verification",
        r"(new|suspicious) sign-?in",
        r"\byour pin\b",
    ),
)

# Storage quota warnings — Gmail, Drive, Photos.
_ACCOUNT_STORAGE = NonJobRule(
    name=ACCOUNT_STORAGE,
    patterns=_compile(
        r"storage is (almost )?full",
        r"out of storage",
        r"running out of space",
        r"хранилище",
        r"больше не можете загружать",
    ),
)

# Product, policy and compliance notices from a platform's own operations.
_SERVICE_NOTICE = NonJobRule(
    name=SERVICE_NOTICE,
    patterns=_compile(
        r"\[action (advised|required)\]",
        r"privacy (policy|settings)",
        r"настройки конфиденциальности",
        r"terms of (service|use)",
        r"policy update|updated? our (policy|policies|terms)",
        r"profiles are now synced",
    ),
)

# Money mail. Patterns are phrase-anchored: a bare "payment" would reject
# "Senior Engineer - Payments at Kraken".
_BILLING_NOTICE = NonJobRule(
    name=BILLING_NOTICE,
    patterns=_compile(
        r"your (invoice|receipt|payment)\b",
        r"\breceipt for\b",
        r"\binvoice #",
        r"payment (failed|declined|received|method)",
        r"subscription (has )?(renew|expir|cancel|end)",
        r"billing (issue|problem|update|information)",
    ),
)

# Onboarding and profile-completion nudges. These promote the platform, not a role.
_PLATFORM_ONBOARDING = NonJobRule(
    name=PLATFORM_ONBOARDING,
    patterns=_compile(
        r"^welcome to\b",
        r"complete your (profile|application|registration)",
        r"complete vetting",
        r"upload your (resume|cv)",
        r"all-?star profile",
        r"(a )?few more steps",
        r"finish (setting up|your) (profile|account)",
    ),
)

# Unsubscribe and preference confirmations.
_SUBSCRIPTION_CHANGE = NonJobRule(
    name=SUBSCRIPTION_CHANGE,
    patterns=_compile(
        r"you(’|')?re unsubscribed",
        r"unsubscribe(d)? (confirm|success)",
        r"email preferences updated",
    ),
)

# "Your job alert is now active" confirms a saved search; it carries no jobs.
# Swedish (jobbevakning) and Dutch (vacature-alert) variants arrive from Indeed.
_ALERT_ACTIVATION = NonJobRule(
    name=ALERT_ACTIVATION,
    patterns=_compile(
        r"job alert .* is now active",
        r"jobbevakning .* (är|ar) nu aktiv",
        r"vacature-alert .* is nu actief",
    ),
)


NON_JOB_RULES: tuple[NonJobRule, ...] = (
    _LINKEDIN_SOCIAL,
    _ACCOUNT_SECURITY,
    _ACCOUNT_STORAGE,
    _SERVICE_NOTICE,
    _BILLING_NOTICE,
    _PLATFORM_ONBOARDING,
    _SUBSCRIPTION_CHANGE,
    _ALERT_ACTIVATION,
)


def match_non_job_rule(subject: str, platform: str | None) -> str | None:
    """Return the name of the first rule that rejects this subject, else None."""
    for rule in NON_JOB_RULES:
        if rule.matches(subject, platform):
            return rule.name
    return None
