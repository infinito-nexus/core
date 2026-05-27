# javascript.js

This page covers automatically generating and updating role-local `javascript.js`, `javascript.js.j2`, and equivalent injected browser entry files.
Use this page for implementation scope, DOM strategy, and live review.
For injector wiring, activation, and repository-wide behavior rules, see [Contributing `javascript.js`](../../../contributing/artefact/files/role/javascript.js.md).

## Goal

- You MUST use role-local JavaScript only for browser-side gaps that cannot be solved cleanly through app configuration, server configuration, or CSS alone.
- Keep injected scripts small, explicit, and tightly scoped to the role's real integration need.
- Write the result so it adapts the upstream UI without turning the injected script into a fork of the application's frontend.

## Implement

- You MUST use `templates/javascript.js.j2` when runtime values from the inventory or role variables must be rendered into the browser code.
- You MUST use `files/javascript.js` when the script is static and does not depend on templating.
- You MUST wait for the DOM before touching elements, and guard missing elements so unrelated pages do not break.
- You MUST keep event handlers, observers, and DOM mutations idempotent because injected scripts may run on dynamic pages or be triggered repeatedly.
- You MUST prefer stable selectors and narrow hooks over text matching or timing-based hacks.

## Avoid

- Do NOT reimplement server-side logic, authentication protocols, or business rules in injected JavaScript.
- Do NOT rewrite large parts of the frontend when a focused event handler, DOM adjustment, or configuration change is enough.
- Do NOT rely on fragile selectors, broad text matching, or timing hacks when more stable hooks exist.
- Do NOT introduce noisy debug logging, uncaught errors, duplicate event handlers, or endless observers into injected scripts.
- Do NOT break native login, logout, navigation, or form flows unless the role explicitly requires that change and the new behavior is verified end to end.

## Review

- You MUST check the result with live inspection in the running application, not only by reading the JavaScript file.
- You MUST compare the implemented behavior against the rendered UI so missing hooks, duplicate handlers, broken selectors, and unexpected side effects become visible.
- You MUST at minimum inspect and compare the start page and the login page because these pages usually expose the most important navigation, authentication, and first-load behavior.
- You MUST check the browser console for JavaScript errors or repeated side effects after the script is injected.
- If the change affects user-visible behavior, you MUST add or update the matching end-to-end coverage in [Role `playwright.spec.js`](playwright.spec.js.md).
- You MUST check that the final JavaScript still feels like a small role-local adaptation of the target application, not a forked frontend implementation.
