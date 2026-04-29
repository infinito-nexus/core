# `playwright.spec.js` 🎭

This page is the primary SPOT for what a role-local `files/playwright.spec.js` MUST contain in a `web-*` role's Playwright suite. All scenario, selector, and final-state rules live here.
For framework, runner wiring, and the central image pin, see [Playwright Tests](../../../actions/testing/playwright.md).
For the agent-specific authoring procedure (how to generate and review the file automatically), see [Agent `playwright.spec.js`](../../../../agents/files/role/playwright.spec.js.md).
For the matching rendered environment contract, see [Agent `playwright.env.j2`](../../../../agents/files/role/playwright.env.j2.md).

## File Placement 📁

- You MUST place the spec at `roles/<role>/files/playwright.spec.js`.
- The central-vs-per-role rule for `package.json` and `playwright.config.js` is owned by the framework SPOT. See [Playwright Tests: Role-Local Files](../../../actions/testing/playwright.md#role-local-files-).

## Entry Point 🚪

- The flow MUST start at `APP_BASE_URL`.
- When the role exposes the dashboard entry (`services.dashboard.enabled` is set), the first navigation MUST go through the dashboard, not straight into the app.

## Scenarios 🎬

- Every spec MUST verify login AND logout end to end. No scenario may finish while the session is still authenticated.
- Every scenario MUST reflect the role's actual post-login behavior, not only that a URL loaded. Assert on a user-visible state that confirms the session is genuinely active (an authenticated-only element, a user menu, or an accessible admin area) instead of stopping at URL assertions or static text checks.
- Every persona the role supports MUST have its own scenario. For roles covering both `biber` and `administrator`, keep one scenario per persona. Do not overload a single test with two identities.
- When the role enables OIDC or LDAP, at least one scenario MUST exercise the integrated login path so the auth-flow wiring is covered end to end (not only the local-form login).
- A scenario MUST be added or updated whenever role-local `style.css` or `javascript.js` changes user-visible behavior, asserting on the visible effect.
- When the application supports peer-to-peer messaging, the spec MUST cover a bi-directional exchange between `biber` and `administrator`: `biber` sends a direct message to `administrator` AND `administrator` sends one back, each delivery asserted in the recipient's inbox from an isolated browser context.
- Existing scenarios MUST NOT be deleted when optimizing a spec. Rewrite them to satisfy the MUSTs above or strengthen their assertions, but do not shrink coverage by removing a scenario — deletions are only acceptable when the underlying behavior has been removed from the role itself.

## Selectors and Waits ⏳

- Selectors MUST prefer accessible roles, form-scoped buttons, and other stable hooks over brittle DOM lookups or generic labels that can match unrelated UI (e.g. topbar search vs. login submit).
- Waits MUST target meaningful page state (visible elements, URL changes, attached locators). Fixed sleeps MUST NOT be used where an explicit wait is available.
- When a flow runs inside an iframe and login or OIDC clicks can reload it, the spec MUST treat the reload as a navigation event: await the next visible state or the new iframe URL, then reacquire the frame and rebuild locators before the next interaction. A stale iframe handle MUST NOT be reused across redirects, and the spec MUST NOT "click and observe the failure" against a frame it already knows will have been replaced.

## Environment Contract 🔌

- Every environment variable the spec reads MUST be exposed in the role's `templates/playwright.env.j2`. Names MUST match exactly on both sides.
- URLs, domains, and credentials MUST NOT be hardcoded in the spec. They MUST come from the rendered `.env`.

## Service Gating 🚦

- A scenario that depends on a shared service (OIDC, LDAP, email, matomo, matrix, mastodon, federation, nextcloud search, onlyoffice, collabora, libretranslate, etc.) MUST gate its execution on that service being enabled in the current deployment. The gate MUST use the shared `isServiceEnabled(name)` or `requireService(name, testFn)` helper, not an ad-hoc env read.
- Service enablement MUST be expressed in the rendered `.env` as one boolean variable per gateable service, named `<SERVICE>_SERVICE_ENABLED` in UPPER_SNAKE_CASE (for example `OIDC_SERVICE_ENABLED=true`, `EMAIL_SERVICE_ENABLED=false`, `MATOMO_SERVICE_ENABLED=false`). Values MUST be the literal strings `"true"` or `"false"`. Specs MUST NOT read these variables directly; they go exclusively through the helper.
- The helper MUST hard-fail with a `Unknown service: <name>` error when called with an identifier that is not declared in the role's Playwright-env registry. This makes a typo in `isServiceEnabled("oicd")` a test error instead of a silent disable.
- The gate MUST use Playwright's native `test.skip()` so the reporter shows the scenario as `skipped` with a reason naming the disabled service (e.g. `skipped: EMAIL_SERVICE_ENABLED=false`). A scenario MUST NOT silently return early, and MUST NOT be wrapped in `test.describe.skip()` under conditions that are only known at runtime.
- Baseline scenarios (reachability, CSP, canonical-domain DOM assertion, logged-out final state) MUST NOT gate on any service. Disabling every shared service MUST still leave a passing baseline suite for the role.
- When the role's own compose service IS the shared service under test (e.g. the Keycloak spec running against Keycloak itself), the admin-facing baseline MUST NOT gate on that service. Gate only the scenarios that assert a downstream integration (e.g. LDAP federation).
- When a `<SERVICE>_SERVICE_ENABLED` variable is absent from the env (local iteration via `scripts/tests/e2e/rerun-spec.sh` against an older staged `.env`), the helper MUST treat that service as enabled. This preserves the current behaviour for iterative spec development against a fully-featured deploy. An explicit `<SERVICE>_SERVICE_ENABLED=false` MUST be the only way to trigger a skip.
- The role's `templates/playwright.env.j2` MUST render every `<SERVICE>_SERVICE_ENABLED` flag the spec references, derived from `applications[<role>].services.<name>.enabled` minus `SERVICES_DISABLED`. The env template IS the registry: a service that the spec may gate on MUST be declared there.

## Final State ✅

- Every scenario MUST end with the browser in a clearly logged-out state.
- The browser console MUST be clean of errors when the flow depends on injected JavaScript.
