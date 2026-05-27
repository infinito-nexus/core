# `style.css`

This page covers automatically generating and updating role-local `style.css`, `style.css.j2`, and equivalent CSS entry files.
Use this page for implementation scope, override strategy, and live review.
For repository wiring, inventory keys, and the generated palette contract, see [Contributing `style.css`](../../../contributing/artefact/files/role/style.css.md).

## Goal

- You MUST add the smallest possible theming layer on top of the role's existing CSS.
- You MUST prefer token mapping over selector rewrites so the role keeps its native structure.
- The result MUST feel like one coherent brand theme, not a collection of unrelated overrides.
- The result MUST be visually appealing and pleasant for humans to look at.

## Color Categories

- You MUST use `--color-01-*` and `--color-rgb-01-*` as the primary palette. They MUST cover the majority of themed surfaces.
- Semantic state colors such as warnings, errors, and success indicators SHOULD keep their original application colors. You MUST add a contrast border in `--color-01-00` or `--color-01-99` around them so they remain visually integrated.
- Categories `02`–`09` MAY be used but are NOT RECOMMENDED. Prefer `--color-01-*` for all surfaces where possible.
- If the application's primary background is dark or black, you MUST use `--color-01-00` as the default theme color. If it is light or white, you MUST use `--color-01-99`. All other application colors MUST be mapped to one of these two anchors. Colors from categories `02`–`09` MUST be derived from and kept in visual relation to the chosen anchor.

## Replace

- You MUST replace hard-coded theme values: colors, RGB channels, gradients, borders, shadows, overlays, placeholder and focus colors.
- You MUST map `--color-01-*` and `--color-rgb-01-*` onto existing framework or app variables first. Add selector-level overrides only when variable mapping is insufficient.
- You MUST replace related values together: surface color, text color, border, hover, active, disabled, and alpha variants.

## Do Not Replace

- You MUST NOT replace layout, spacing, sizing, positioning, z-index, overflow, animation timing, or component structure.
- You MUST NOT replace semantic behavior, JavaScript hooks, or framework-specific class wiring.
- You MUST NOT rewrite large upstream style blocks when a focused override or token remapping is enough.

## Workflow

1. Preserve the role's base CSS so the application styling stays intact.
2. Inspect which variables the role or framework already exposes (semantic tokens, palette variables, custom properties).
3. Map the repository palette onto those variables. Add selector overrides only for surfaces that cannot be reached through variables.
4. Keep gradients, transparency, text contrast, and surface hierarchy aligned.

## Review

- You MUST verify that primary actions, links, forms, cards, dialogs, navigation, and overlays still belong to the same visual system.
- You MUST verify readable contrast for normal, hover, focus, active, and disabled states.
- You MUST inspect the running application, at minimum the start page and login page.
- If the change affects user-visible behavior, you MUST add or update the matching end-to-end coverage in [Role `playwright.spec.js`](playwright.spec.js.md).
