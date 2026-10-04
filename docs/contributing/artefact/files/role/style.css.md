# `style.css` 🎨

This page covers role-local CSS and theming.
Use this page for repository wiring, inventory keys, and the design token contract.
For implementation scope, override strategy, and live review, see [Agent `style.css`](../../../../agents/files/role/style.css.md).
For browser-side validation requirements after visible UI changes, see [Playwright Tests](../../../actions/testing/playwright.md).

## `style.css.j2` ⚙️

- A role ships its override as `templates/style.css.j2` or `files/style.css`.
- `sys-front-inj-design` renders it when `services.design.enabled` is enabled.
- The shared element styles (`body`, links, buttons, form fields, tables, focus outline) sit in the cascade layer `infinito-design`. Every unlayered rule of the app wins over them, so they only style what the app leaves unstyled.
- An app with its own design system gets the corporate palette by mapping its CSS variables onto the tokens in the role stylesheet (see [web-app-gitea](../../../../../roles/web-app-gitea/templates/style.css.j2)), or through its own theming mechanism (Nextcloud takes the primary color, logo, name and slogan via `occ theming:config` and ships no stylesheet).
- The Bootstrap mapping in `bootstrap.css` is unlayered and applies to every Bootstrap app.
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
| `--design-surface-hover`, `--design-surface-active` | Hovered and pressed or open neutral controls; body text stays AAA and muted text AA on both |
| `--design-text` | Body text, AAA against every surface |
| `--design-text-muted` | Secondary text, AA against every surface |
| `--design-border` | Decorative dividers |
| `--design-border-strong` | Input and control boundaries, 3:1 against surfaces |
| `--design-primary` / `--design-on-primary` | Brand surfaces and the text on them |
| `--design-link` | Links and focus, AA against surfaces |
| `--design-success`, `--design-warning`, `--design-danger`, `--design-info` | Status text and icons, AA against surfaces |
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
