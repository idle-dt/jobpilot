"""Custom Jinja2 filters for template rendering."""

import json
import re

from markupsafe import Markup, escape

HIGHLIGHT_CLASS_POSITIVE = "hl-positive"
HIGHLIGHT_CLASS_NEGATIVE = "hl-negative"


def highlight_signals(text: str, matched_signals_json: str | None) -> Markup:
    """Escape text, then wrap matched signal keywords in <mark> tags."""
    if not text or not matched_signals_json:
        return Markup(escape(text or ""))

    escaped = str(escape(text))

    try:
        signals = json.loads(matched_signals_json)
    except (json.JSONDecodeError, TypeError):
        return Markup(escaped)

    # Build replacements: longer keywords first to avoid partial matches
    replacements: list[tuple[str, str]] = []
    for kw in signals.get("positive", []):
        replacements.append((kw, HIGHLIGHT_CLASS_POSITIVE))
    for kw in signals.get("negative", []):
        replacements.append((kw, HIGHLIGHT_CLASS_NEGATIVE))
    replacements.sort(key=lambda x: len(x[0]), reverse=True)

    # Drop keywords that are substrings of a longer matched keyword
    filtered: list[tuple[str, str]] = []
    for kw, css_class in replacements:
        kw_lower = kw.lower()
        if not any(kw_lower in longer.lower() and kw_lower != longer.lower()
                    for longer, _ in filtered):
            filtered.append((kw, css_class))

    for keyword, css_class in filtered:
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        escaped = pattern.sub(
            lambda m, c=css_class: f'<mark class="{c}">{m.group(0)}</mark>',
            escaped,
        )

    return Markup(escaped)
