# `style.css`

This page covers automatically generating and updating role-local `style.css`, `style.css.j2`, and equivalent CSS entry files.
Use this page for implementation scope, override strategy, and live review.
For repository wiring, inventory keys, and the generated palette contract, see [Contributing `style.css`](../../../contributing/artefact/files/role/style.css.md).

## Goal

- You MUST use the app's own configuration before the role stylesheet. An in-house theming, theme or custom CSS option outranks injected CSS.
- You MUST add the smallest possible theming layer on top of the role's existing CSS.
- You MUST prefer token mapping over selector rewrites so the role keeps its native structure.
- The result MUST feel like one coherent brand theme, not a collection of unrelated overrides.
- The result MUST be visually appealing and pleasant for humans to look at.

## Tokens

- You MUST use the semantic `--design-*` tokens listed in [Contributing `style.css`](../../../contributing/artefact/files/role/style.css.md#design-tokens-) for every color. Hard-coded colors are forbidden.
- You MUST prefer semantic tokens (`--design-surface-*`, `--design-text*`, `--design-border*`, `--design-primary`, `--design-link`, status tokens) over the `--design-primary-*` and `--design-neutral-*` scales. Use a scale step only for brand accents a semantic token does not cover.
- You MUST map the app's status colors onto `--design-success`, `--design-warning`, `--design-danger` and `--design-info`, and the text on filled status surfaces onto the matching `--design-on-*` token.
- You MUST map brand-colored app chrome (sidebar, masthead, top bar) onto `--design-frame`, its text and icons onto `--design-on-frame`, and its hovered and selected entries onto `--design-frame-hover` and `--design-frame-active`. `--design-primary` is the accent of controls and MUST NOT fill a large area. On the frame element you MUST set `--design-focus: var(--design-on-frame)`, and set it back to `var(--design-link)` on a surface the frame hosts (a popup, a menu).
- You MUST NOT add your own `prefers-color-scheme` block for colors. The tokens switch with the mode.
- If the app has its own theme switch, you MUST mirror its state onto `<html data-design-theme="light|dark">` from `templates/design.js.j2` so the tokens follow the app, not only the browser.

## Replace

- You MUST replace hard-coded theme values: colors, RGB channels, gradients, borders, shadows, overlays, placeholder and focus colors.
- You MUST map `--design-*` tokens onto existing framework or app variables first. Add selector-level overrides only when variable mapping is insufficient.
- You MUST replace related values together: surface color, text color, border, hover, active, disabled, and alpha variants.
- A text color and its background MUST come from the same source. A token color on an app-owned background, or the reverse, voids the contrast guarantee.
- You MUST map hovered, pressed, open and selected controls onto `--design-surface-hover`, `--design-surface-active` and `--design-<fill>-hover`, `--design-<fill>-active`.
- You MUST verify every variable name you assign against the app's real stylesheet in the running stack. A mapping onto a name the app never reads has no effect.

## Do Not Replace

- You MUST NOT replace layout, spacing, sizing, positioning, z-index, overflow, animation timing, or component structure.
- You MUST NOT replace semantic behavior, JavaScript hooks, or framework-specific class wiring.
- You MUST NOT rewrite large upstream style blocks when a focused override or token remapping is enough.

## Workflow

1. Preserve the role's base CSS so the application styling stays intact, including its contrast relations (frame against content, panel against page, selected against unselected).
2. When the app has its own theming configuration (config, CLI, API or admin setting), feed the palette through it and ship no stylesheet.
3. When the app has an in-house theme or custom CSS option (theme file, custom CSS setting), ship the mapping through that option instead of the role stylesheet.
4. Use the role stylesheet only for what no in-house option reaches. Inspect which variables the role or framework already exposes (semantic tokens, palette variables, custom properties).
5. Map the design tokens onto those variables. Add selector overrides only for surfaces that cannot be reached through variables.
6. Keep transparency, text contrast, and surface hierarchy aligned. Replace upstream gradients with flat token surfaces.

The full role pass, the review gallery and the work queue are described in the [Design Loop](../../action/design.md).

## Review

- You MUST verify that primary actions, links, forms, cards, dialogs, navigation, and overlays still belong to the same visual system.
- You MUST verify readable contrast for normal, hover, focus, active, and disabled states.
- You MUST inspect the running application in light and dark mode, at minimum the start page and login page, and the backend (admin surface) when the app has one.
- If the change affects user-visible behavior, you MUST add or update the matching end-to-end coverage in [Role `playwright.spec.js`](playwright.spec.js.md).
