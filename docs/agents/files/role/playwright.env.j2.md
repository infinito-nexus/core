# playwright.env.j2

This page is the SPOT for automatically generating and updating role-local `playwright.env.j2` files.
Use this page for the rendered test input surface, variable naming, and entry-point selection.
For runner discovery, staging, and repository-side contract rules, see [Playwright Tests](../../../contributing/actions/testing/playwright.md).
For the matching scenario implementation, see [Role `playwright.spec.js`](playwright.spec.js.md).

## Goal

- You MUST provide only the environment values that the role-local Playwright suite actually needs.
- Variable naming and entry-point semantics are governed by the [contrib SPOT for `playwright.spec.js`](../../../contributing/artefact/files/role/playwright.specs.js.md) (Environment Contract + Entry Point). This page only adds template-side mechanics.
- You MUST render the real entry point, URLs, feature flags, and credentials that the deployed role exposes.

## Implement

- You MUST define `APP_BASE_URL` consistent with the Entry Point rules in the contrib SPOT, in particular the dashboard routing rule when `services.dashboard.enabled` is set.
- Expose app-specific base URLs, issuer URLs, feature flags, and credentials only when the spec consumes them.
- You MUST use `dotenv_quote` for values that may contain spaces, special characters, or shell-sensitive content.
- When the suite covers multiple personas such as `biber` and `administrator`, you MUST expose separate variables for each scenario instead of overloading one shared credential pair.

## Avoid

- Do NOT expose unused variables, duplicate values, or secrets that the spec never reads.
- Do NOT hardcode domains or credentials that should come from role variables, inventory, or lookups.

## Review

- You MUST check that every environment variable referenced in `playwright.spec.js` is present in the rendered `.env` (the name-alignment MUST is owned by the contrib SPOT Environment Contract).
- You MUST check that `APP_BASE_URL`, app URLs, issuer URLs, and feature toggles match the deployed role.
- You MUST check that persona-specific credentials such as `biber` and `administrator` map to the intended scenarios.
