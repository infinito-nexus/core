# playwright.spec.js agent procedure

This page is the SPOT for the agent procedure when generating or updating a role-local `playwright.spec.js`. It does NOT restate what the file must contain. Those rules are authoritative in [Contributing `playwright.spec.js`](../../../contributing/artefact/files/role/playwright.specs.js.md) and MUST be consulted before every task.

For framework and runner mechanics, see [Playwright Tests](../../../contributing/actions/testing/playwright.md).
For the matching environment contract, see [Role `playwright.env.j2`](playwright.env.j2.md).

## Procedure

1. Read the contributor SPOT and treat every MUST there as a non-negotiable acceptance criterion for the generated spec.
2. Inspect the role's `meta/services.yml` (and the matching `meta/server.yml` / `meta/rbac.yml`) and `defaults/main.yml` to determine the supported entry point (dashboard vs. direct app), enabled integrations (OIDC, LDAP, messaging, etc.), and active personas.
3. Read or author the role's `templates/playwright.env.j2` first and keep every variable name aligned with the generated spec.
4. Draft scenarios from the live running stack, not from assumptions. Use Playwright codegen or `playwright-recorder` (see the framework SPOT) as a starting point when the DOM structure is unknown.
5. Deploy the role and run the spec inside the shared `test-e2e-playwright` runner until every MUST in the contributor SPOT passes and the browser console is free of unhandled errors.
6. When the change was triggered by an update to role-local `style.css` or `javascript.js`, verify the new visible behavior is covered before reporting the task complete.

## Live Review

Before reporting the task complete, you MUST verify the spec against a running stack, not against file contents alone. Static file review misses navigation and auth bugs that only surface in the browser.

- You MUST drive the scenarios through a real browser session against the deployed role. A green local file-lint does not satisfy this step.
- You MUST inspect the start page AND the login page of the role as part of the end-to-end run. These two pages surface most navigation, authentication, and first-load regressions that later assertions would only catch indirectly.
- You MUST open the browser console during runs that depend on injected JavaScript and confirm it is free of unhandled errors before reporting success.

## Reporting

- Report which MUSTs in the contributor SPOT were verified end to end and which were covered only by a static check, if any.
- Reference the deploy log path when the run surfaced any anomaly the reviewer should see.
