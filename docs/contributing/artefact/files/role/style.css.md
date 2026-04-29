# `style.css` 🎨

This page is the SPOT for role-local CSS and theming.
Use this page for repository wiring, inventory keys, and palette mapping.
For implementation scope, override strategy, and live review, see [Agent `style.css`](../../../../agents/files/role/style.css.md).
For browser-side validation requirements after visible UI changes, see [Playwright Tests](../../../actions/testing/playwright.md).

## `style.css.j2` ⚙️

- `roles/web-app-taiga/templates/style.css.j2` is the Taiga role override.
- `sys-front-inj-css` renders it when `services.css.enabled` is enabled.
- The template maps the generated palette to semantic variables such as `--color-01-solid-primary`, `--color-01-link-primary`, grayscale steps, and `--color-rgb-01-*`.
- `CSS_GRADIENT_ANGLE` keeps the gradients consistent across surfaces.

## Inventory 📋

- You MUST set `design.css.colors.base` in the inventory as the single base color.
- You MUST keep `services.css.enabled` enabled in the role configuration or override it in the inventory when CSS injection should run.
- You SHOULD add `design.font.import_url` when typography and colors should be controlled together.

## Color Logic 🎨

- The palette is generated from a base color through `colorscheme-generator`.
- Role-local CSS MAY use the full generated palette space: all color categories `01` through `07` and all brightness values `00` through `99`.
- You MUST combine the matching `--color-XX-*` and `--color-rgb-XX-*` tokens in a way that is both meaningful and aesthetically coherent so semantic mappings, surfaces, gradients, borders, and overlays work together as one design system.
