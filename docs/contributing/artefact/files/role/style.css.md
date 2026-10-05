# `style.css` 🎨

This page covers role-local CSS and theming.
Use this page for repository wiring, inventory keys, and the design token contract.
For implementation scope, override strategy, and live review, see [Agent `style.css`](../../../../agents/files/role/style.css.md).
For browser-side validation requirements after visible UI changes, see [Playwright Tests](../../../actions/testing/playwright.md).

## `style.css.j2` ⚙️

- A role ships its override as `templates/style.css.j2` or `files/style.css`.
- `sys-front-inj-design` renders it when `services.design.enabled` is enabled.
- The shared element styles (`body`, links, buttons, form fields, tables, focus outline) sit in the cascade layer `infinito-design`. `layer.css` is linked first in `<head>` and declares that layer before the app's own stylesheets, so every rule of the app wins over them, layered or not. They only style what the app leaves unstyled.
- The app's own configuration outranks the role stylesheet. A theming configuration carries the palette first (Nextcloud takes the primary color, logo, name and slogan via `occ theming:config` and ships no stylesheet), then an in-house theme or custom CSS option.
- An in-house theme carries a variable mapping natively (see [web-app-gitea](../../../../../roles/web-app-gitea/templates/theme.css.j2)). The role stylesheet maps the app's CSS variables onto the tokens only for what no in-house option reaches.
- The Bootstrap component mapping in `bootstrap.css` is unlayered. A role built on Bootstrap links it by setting `bootstrap: true` in its `design:` entry. Set in `web-svc-design`, the value applies to every role.
- A role stylesheet or design script that renders empty counts as absent: nothing is deployed, linked or injected for it.
- A role MAY ship `templates/design.js.j2`. `sys-front-inj-design` collapses it, adds its CSP hash and injects it whenever `services.design.enabled` is enabled, independent of `services.javascript.enabled`.

## Inventory 📋

- You MUST set `applications.web-svc-design.services.design.colors.base` in the inventory as the single base color.
- You MUST keep `services.design.enabled` enabled in the role configuration or override it in the inventory when CSS injection should run.
- You MAY set `applications.web-svc-design.services.design.font.type` and `font.import_url` to change the typography.

## Design Tokens 🎨

The [design_palette](../../../../../plugins/lookup/design_palette.py) lookup derives every token from the base color in OKLCH and guarantees WCAG 2.2 contrast by construction.

| Token | Use |
|---|---|
| `--design-surface-1` | Page background |
| `--design-surface-2` | Cards, panels, inputs |
| `--design-surface-3` | Hover, selected and inset areas, table heads |
| `--design-surface-hover`, `--design-surface-active` | Hovered and pressed or open neutral controls; body text stays AAA, muted text, links and status colors AA on both |
| `--design-text` | Body text, AAA against every surface |
| `--design-text-muted` | Secondary text, AA against every surface |
| `--design-border` | Decorative dividers |
| `--design-border-strong` | Input and control boundaries, 3:1 against `--design-surface-1` and `--design-surface-2` |
| `--design-primary` / `--design-on-primary` | Brand surfaces, 3:1 against `--design-surface-1` and `--design-surface-2`, and the text on them |
| `--design-frame` / `--design-on-frame` | Large brand surfaces such as a sidebar, masthead or top bar: a deep brand tone in light and dark mode, and the text on it at AAA |
| `--design-frame-hover`, `--design-frame-active` | Hovered and selected entries inside the frame; the on-color stays AAA |
| `--design-focus` | Color of the default focus outline. Unset, the outline uses `--design-link`. A frame sets it to `--design-on-frame` on its own element; every focusable it hosts then draws its outline in that color |
| `--design-link` | Links and focus, AA against every surface |
| `--design-success`, `--design-warning`, `--design-danger`, `--design-info` | Status text and icons, AA against every surface and against their own `-subtle` background |
| `--design-on-<status>` | Text on a filled status surface |
| `--design-primary-hover`, `--design-primary-active`, `--design-<status>-hover`, `--design-<status>-active` | Hovered and pressed filled controls, shifted away from their on-color so its contrast only grows |
| `--design-<status>-subtle`, `--design-<status>-border` | Alert backgrounds and borders |
| `--design-primary-50` to `--design-primary-950` | Brand scale |
| `--design-neutral-50` to `--design-neutral-950` | Tinted neutral scale |
| `--design-radius-sm`, `--design-radius`, `--design-radius-lg` | Corner radii |
| `--design-space-1` to `--design-space-6` | 4/8 px spacing steps |
| `--design-shadow-1` to `--design-shadow-3` | Elevation |
| `--design-focus-ring` | Focus indicator for Bootstrap buttons and nav links |
| `--design-focus-ring-inset` | Focus indicator for Bootstrap form fields, drawn inside the field so it never overlaps neighbours |
| `--design-invert` | `0` in light and `1` in dark mode. Use `filter: brightness(0) invert(var(--design-invert))` to render a monochrome image in the text tone |

- Every color token also exists as `<token>-rgb` for `rgba()` use.
- Scale step `50` sits next to the surface and `950` next to the text in light and dark mode, so a mapping onto the scale follows dark mode without a media query.
- Dark mode follows `prefers-color-scheme`. A role whose app has its own theme switch sets `data-design-theme="light"` or `data-design-theme="dark"` on `<html>` from its `design.js.j2`; the attribute wins over the browser preference.
- Role CSS MUST use only `--design-*` tokens for colors. Hard-coded colors break the base color override.
