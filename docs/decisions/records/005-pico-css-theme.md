# ADR-005: Pico CSS with custom theme

**Status:** accepted
**Date:** 2026-05-07
**Tags:** frontend, design

## Context

The UI is server-rendered with Jinja2 + htmx (see [ADR-003](003-flask-jinja2-htmx.md)).
We wanted sensible, accessible default styling for semantic HTML without adopting a
utility-class framework or a build step, but we also wanted a distinctive, warm
"premium editorial" look (the Mastercard-inspired design system in `DESIGN.md`) —
warm cream canvas, ink-black pill CTAs, oversized radii, Sofia Sans — rather than a
generic framework default.

## Decision

Use **Pico CSS v2** (loaded from CDN) as the classless base, then layer a custom
theme on top in `static/style.css`.

- The custom theme defines CSS custom properties for the palette and shape system
  (`--canvas: #F3F0EE`, `--ink: #141413`, `--radius-btn: 20px`, `--radius-pill: 999px`,
  etc.) under `:root`/`[data-theme="light"]`, with a `[data-theme="dark"]` override.
- These variables are bound onto Pico's own variables
  (`--pico-background-color: var(--canvas)`, `--pico-primary: var(--ink)`, …) so Pico
  components pick up the theme.
- Typography uses **Sofia Sans** (Google Fonts) at weight 450 for body and 500 for
  headings with tight negative tracking — Sofia Sans is the closest open-source match
  to Mastercard's proprietary MarkForMC and is in its own fallback stack.
- Theme is toggled via `data-theme` and persisted to `localStorage`.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Tailwind CSS | Requires a build/PostCSS pipeline; utility classes clash with the server-rendered, classless-first approach. |
| Bootstrap | Heavier, opinionated component look that fights the bespoke warm-editorial design. |
| Hand-written CSS from scratch | Loses Pico's accessible defaults for semantic elements; more boilerplate before reaching the custom layer. |
| MarkForMC (the reference font) | Proprietary and licensed; Sofia Sans is the documented open-source substitute. |

## Consequences

### Positive
- Accessible, good-looking defaults for semantic HTML with no build step.
- Custom-property theming gives full control over palette/shapes and clean dark mode.
- CDN delivery keeps the repo free of vendored CSS.

### Negative / Tradeoffs
- Overriding Pico defaults (e.g. neutralizing button styles for pill CTAs) sometimes needs `!important`.
- CDN dependency for the base stylesheet (mitigated by SRI integrity hash).

### Risks
- Pico v3 could change variable names and require theme rework.

## Related

- ADRs: [ADR-003](003-flask-jinja2-htmx.md) (Flask + Jinja2 + htmx UI)
- Code: `src/jobpilot/web/static/style.css`, `src/jobpilot/web/templates/base.html`
- Docs: `DESIGN.md` (full design system rationale)
