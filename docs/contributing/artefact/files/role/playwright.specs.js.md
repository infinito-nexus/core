# `playwright.spec.js` 🎭

This page describes what every role's `roles/<role>/files/playwright/playwright.spec.js` MUST contain: file placement, the two persona flows, per-service assertions, technical rules, and final-state guarantees.

For framework and runner mechanics see [Playwright Tests](../../../actions/testing/playwright.md).
For the authoring procedure see [Agent `playwright.spec.js`](../../../../agents/files/role/playwright.spec.js.md).
For the env contract see [Agent `playwright.env.j2`](../../../../agents/files/role/playwright.env.j2.md).

## File placement 📁

- The spec MUST be at `roles/<role>/files/playwright/playwright.spec.js`. The role-relative path is the SPOT constant `ROLE_FILE_PLAYWRIGHT_SPEC` in [mapping.py](../../../../../utils/roles/mapping.py); registered as optional on `ROLE_TYPE_APPLICATION`, disallowed elsewhere.
- Companion `.js` helpers (role-local utility modules, like `web-app-dashboard/files/playwright/dashboard-card-flow.js`) MAY live next to the spec under the same `files/playwright/` directory. The runner (`roles/test-e2e-playwright/tasks/02_run_one.yml`) globs every `*.js` in that directory and stages them into the same `tests/` tree, so the spec can `require("./<helper>")` without any further wiring.
- `playwright.config.js` and `package.json` are central, NOT per-role. See [Playwright Tests → Role-Local Files](../../../actions/testing/playwright.md#role-local-files-).

## Three personas, fixed flow 🚶

Every spec MUST include the three persona scenarios below as its baseline.
Additional scenarios (RBAC loops, peer-to-peer messaging, federation round-trips, CSP-deep-checks, …) MAY be added on top.
Three personas exist in the deploy fixture: `guest` (no Keycloak account), `biber` (regular end-user), and `administrator` (operator/admin).
The flow shape is identical across roles.
Only the role-specific selectors and the post-login assertion change.
Service-dependent steps MUST be guarded with [`skipUnlessServiceEnabled('<svc>')`](../../../../../roles/test-e2e-playwright/files/service-gating.js) so a deploy with `INFINITO_SERVICES_DISABLED=<svc>` reports the affected step as `skipped: <NAME>_SERVICE_ENABLED=false`, never `failed`.

Each persona scenario MUST be named `<persona>: <flow>`, where `<persona>` is the literal token `guest`, `biber`, or `administrator` and `<flow>` is a concise step description (e.g. `dashboard → app → logout`).
The persona token MUST appear at the very start of the test title so the Playwright reporter groups runs by persona without further parsing.

Roles that have no auth surface at all (federation-only services with no local accounts, e.g. `web-app-bridgy-fed`) MAY collapse the three persona scenarios into one baseline reachability scenario.
The README MUST document the missing auth tier and the omission MUST be visible from the role's `lifecycle` and `services.yml` exceptions.

When the docs and the spec disagree, the spec wins.
Documentation MUST be brought into alignment, not the other way around.

### `guest`: cannot log in anywhere

```
[ ${APP_BASE_URL}/ ]                    no skip; the guest scenario is always live
        │  optional click on a "log in" / "sign in" link
        ▼
[ public landing OR auth chain ]        assert: CSP injections valid
                                        assert: NEVER lands on the role's
                                                authenticated surface;
                                                empty-credentials submission
                                                MUST be rejected by the IdP
```

### `biber`: single-app authenticated journey

```
[ ${APP_BASE_URL}/ ]                    direct goto, bookmark-style entry
        │  oauth2-proxy redirects unauthenticated requests to Keycloak
        ▼
[ Keycloak auth chain ]                 skipUnlessServiceEnabled('oidc' | 'oauth2' | 'ldap')
        │  Keycloak login (biber)
        ▼
[ authenticated app ]                   assert: user-visible authenticated element
                                        assert: CSP injections valid
        │  drive role-specific interaction (biberInteraction callback)
        │  click universal logout / in-app logout button
        ▼
[ unauthenticated landing ]             assert: protected request re-engages auth
```

Cross-service probes (biber denied at prometheus, biber denied at matomo, dashboard tile reachability) are NOT part of the per-role biber persona.
They live in the provider's own spec (`web-app-{prometheus,matomo,dashboard}/files/playwright/playwright.spec.js`), parameterised once over the provider's `<NAME>_TARGET_ROLES_JSON` manifest.
For the dashboard, the parameterised scenario delegates to `web-app-dashboard/files/playwright/dashboard-card-flow.js::runDashboardCardScenario(page, context, target)`, which owns the tile visibility / iframe-embed / "Tab" pop-out assertions in one SPOT.

### `administrator`: single-app authenticated journey

```
[ ${APP_BASE_URL}/ ]                    direct goto, bookmark-style entry
        │  oauth2-proxy redirects unauthenticated requests to Keycloak
        ▼
[ Keycloak auth chain ]                 skipUnlessServiceEnabled('oidc' | 'oauth2' | 'ldap')
        │  Keycloak login (administrator)
        ▼
[ authenticated app ]                   assert: admin-visible element
                                        (admin panel, management menu, ...)
                                        assert: CSP injections valid
        │  drive admin-only interaction (adminInteraction callback)
        │  click universal logout / in-app logout button
        ▼
[ unauthenticated landing ]             assert: protected request re-engages auth
```

Cross-service probes are NOT part of the per-role administrator persona.
Dashboard tile reachability is owned by `web-app-dashboard/files/playwright/playwright.spec.js`, which delegates the per-target body to the `runDashboardCardScenario` helper in `dashboard-card-flow.js` (tile visible → click loads in `#main iframe` → header "Tab" button pops the embed into a fresh browser tab). That helper is the SPOT for dashboard-tile mechanics; consumer specs MUST NOT reimplement any of those assertions.
Prometheus admin-reach and scrape parity are owned by `web-app-prometheus/files/playwright/playwright.spec.js`.
Matomo admin-reach and tracker presence are owned by `web-app-matomo/files/playwright/playwright.spec.js`.
Each provider parameterises the assertion over its `<NAME>_TARGET_ROLES_JSON` manifest.

### Test-body template

```js
const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runGuestFlow, runBiberFlow, runAdminFlow } = require("./personas");

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → keycloak → role action → logout", async ({ page }) => {
  await runBiberFlow(page, { biberInteraction: async (p) => { /* role-specific */ } });
});

test("administrator: app → keycloak → admin action → logout", async ({ page }) => {
  await runAdminFlow(page, { adminInteraction: async (p) => { /* admin-only */ } });
});
```

### Role-specific interactions and peer exchange (every spec, every role)

A persona scenario that only logs in and logs out is NOT enough.
After the auth chain settles (or directly on the role surface when no auth is required), every persona MUST drive a real, app-specific interaction so the spec proves the role is responsive to user input, not just reachable.

- The `biber` persona MUST drive at least one role-specific interaction that a regular end-user would perform (post a message, open a settings tab, browse a content list, submit a form, …).
  Specs supply this via the `biberInteraction` callback on `runBiberFlow(page, { biberInteraction })`.
  There is NO generic default.
  A generic "click any link" assertion tests nothing role-specific, so the helper is a no-op until the spec provides a callback.
- The `administrator` persona MUST drive at least one admin-only interaction (admin panel toggle, realm settings change, user-management surface, …).
  Specs supply this via the `adminInteraction` callback on `runAdminFlow(page, { adminInteraction })` under the same "no generic default" rule.
- When the role supports peer-to-peer interaction (messaging, comment threads, federation round-trips, calendar invites, …), the spec MUST include a separate `biber ↔ administrator: <flow>` test that opens two browser contexts, drives the round-trip end-to-end, and asserts both sides see the expected payload.
  The shared `runPeerExchangeFlow(browser, { peerExchange })` helper provides the two-context scaffolding.
  The role-specific message, payload, and assertion live in the spec.
- Roles whose upstream offers no peer interaction surface (every static, single-purpose, or federation-only role on the auth-less list) MUST NOT add a peer-exchange test.
  The omission is part of the role's contract, not a gap.

The role-specific interaction callbacks and the peer-exchange test are part of the persona contract.
Specs that ship only the personas without an interaction callback fulfil the bare minimum, but SHOULD extend with bespoke role coverage during the role's rollout iteration.

### Strict failure on un-executable persona cases

A persona scenario MUST fail loudly when its contracted journey cannot execute end-to-end.
A silent `test.skip(...)` on runtime detection of "no logout button", "no authenticated surface", or "no admin UI marker" is FORBIDDEN.
Silent skips hide real regressions (broken OIDC mapping, removed logout button, misconfigured oauth2-proxy, drifted UI selectors) behind a green deploy.

The ONLY clean-skip mechanism is an EXPLICIT role-declared opt-out via env flag rendered in `templates/playwright.env.j2`:

```
PERSONA_BIBER_BLOCKED=true
PERSONA_ADMINISTRATOR_BLOCKED=true
PERSONA_GUEST_BLOCKED=true
```

Each flag MUST be accompanied by a one-line `# nocheck` comment above the env line stating the role contract that justifies blocking the persona, and a matching paragraph in the role's `README.md` (or `TODO.md` while the rationale is still drafting).
Without the flag, the persona helper hard-fails the test with a diagnostic naming the last-seen URL and pointing the operator at two repair paths: fix the auth chain, or declare the opt-out flag.

Direct-probe deny-checks MUST validate the response body, not only the status code.
A `200 OK` is acceptable ONLY when the body contains provider-specific markers proving the response is the genuine provider surface.
For prometheus, the markers are `prometheus_build_info` or `<title>Prometheus</title>`.
For matomo, the markers are matomo's login-form markers or `piwik` and `matomo` strings in the body.
Any 200 with a non-matching body is treated as a misconfigured proxy or a denial-as-200 surface and fails loudly.
The deny-checks live in the provider's own spec (`web-app-prometheus/files/playwright/playwright.spec.js` and `web-app-matomo/files/playwright/playwright.spec.js`).

### Invariants (every spec, every role)

- All three personas (`guest`, `biber`, `administrator`) start at `${APP_BASE_URL}/` via direct goto (bookmark-style entry).
  The OAuth2-Proxy gate fires on the first request and redirects unauthenticated requests through Keycloak.
  No dashboard-tile click sits in the persona path.
- The `biber` and `administrator` personas always end on a verified unauthenticated landing via the in-app logout button.
- The `guest` persona MUST never reach the role's authenticated surface.
  An empty-credentials submission against Keycloak MUST be rejected by the IdP.
- Cross-service surface assertions (dashboard tile reachability, prometheus admin-reach and scrape parity, matomo admin-reach and tracker presence, biber-denied-at-prometheus, biber-denied-at-matomo) are owned by the provider's own spec.
  Each provider parameterises the assertion over its `<NAME>_TARGET_ROLES_JSON` manifest, rendered via `lookup('roles_with_service', '<svc>')`.
  Consumer roles' personas MUST NOT duplicate these probes.
- Every persona scenario MUST run the CSP injection assertion at least once on the role's canonical surface.
  When an injector service (`asset`, `cdn`, `css`, `javascript`, `simpleicons`, `matomo`) is enabled, the page's `Content-Security-Policy` header MUST list the injector's host.
  The assertion is centralised in [`personas/utils/csp.js`](../../../../../roles/test-e2e-playwright/files/personas/utils/csp.js) so every spec gets the check by default.
- The full CSP test surface lives in the same module: `assertCspResponseHeader(response, label)` (returns the parsed directive map), `assertCspMetaParity(page, headerDirectives, label)` (verifies the optional `<meta http-equiv>` echo is a subset of the response header), `installCspViolationObserver(page)` + `readCspViolations(page)` (DOM-side `securitypolicyviolation` capture), `expectNoCspViolations(page, diagnostics, label)` (asserts neither the DOM stream nor `diagnostics.cspRelated` carries a violation), and the `EXPECTED_CSP_DIRECTIVES` constant.
  Specs MUST require these from `./personas`; inline copies are forbidden and caught at review.
- Every service-dependent step uses `skipUnlessServiceEnabled(...)`.
  Direct `process.env` reads of `<NAME>_SERVICE_ENABLED` are forbidden.
- Baseline scenarios (reachability, CSP, canonical-domain DOM assertion, logged-out final state) MUST NOT gate on any service.
  A deploy with every shared service disabled MUST still leave a passing baseline suite.
- When the role enables both `oidc` and `ldap`, each persona's primary login path MUST use OIDC.
  Each persona MUST additionally implement a dedicated LDAP scenario gated on `skipUnlessServiceEnabled('ldap')` so the scenario fires whenever LDAP is enabled.
- Each `test()` runs in its own isolated browser context.
  Specs MUST NOT share session state between tests.
  Running biber and administrator as two separate `test()` blocks already gives that isolation by default.
  When a single scenario needs more than one identity at once (peer-to-peer messaging, RBAC promotion observed by the admin, …), it MUST open a fresh `browser.newContext({ ignoreHTTPSErrors: true })` per identity and close them in `finally`.
- The post-login assertion MUST prove the session is real, in this order of preference: a user-menu or persona-name string visible in the DOM, a navigation element only rendered for authenticated users, a URL pattern unique to authenticated state.
  Stopping at a 2xx status code or a static text snippet that exists logged-out as well MUST NOT count as a session check.
- The admin assertion MUST additionally prove admin authorisation (admin panel, management menu, "Users" / "Settings" / "Administration" link visible in the DOM).
  A scenario that lands on the same surface as `biber` and stops there MUST NOT claim admin coverage.
- Every spec MUST set `test.use({ ignoreHTTPSErrors: true })` at the top of the file because the test environment uses self-signed certificates.
  The central `playwright.config.js` does NOT set this globally.
  Per-spec opt-in is the contract.
- Test titles MUST follow the `<persona>: <flow>` naming convention so the reporter groups runs by persona without parsing.

## No stub tests 🚫

Every `test()` body in `files/playwright/playwright.spec.js` MUST simulate the user flow the title promises and assert on a user-visible state.
Stubs are forbidden:

- A body that contains only `skipUnlessServiceEnabled(...)` (or any combination of helper calls) without at least one `expect(...)`, `await <fn>(...)`, or equivalent real-flow step is rejected.
- A body that carries a `TODO`, `STUB`, `FIXME`, or `XXX` marker is rejected.
  The contract requires real flows, not deferred work.
- An empty body is rejected.
- A body that asserts only constants (`expect(1).toBe(1)`) without driving any role surface is rejected on review.

The persona scenarios MUST drive the journey from [Three personas, fixed flow](#three-personas-fixed-flow-) end to end.
Per-service contract tests MUST exercise the [per-service assertion catalogue](#per-service-assertion-catalogue-) entry that matches their gated service.
The [test_no_stub_tests.py](../../../../../tests/lint/ansible/roles/web-app/playwright/test_no_stub_tests.py) lint hard-fails the build when a stub is detected, so the rule is enforced automatically.

## No direct URL clicks for user actions 🚫

Tests MUST simulate real user behaviour by interacting with the rendered UI.
Navigating directly to an action endpoint via `page.goto(<endpoint>)` is FORBIDDEN whenever a click target exists on the current surface.
The most common offender is logout: a test MUST click a logout button or a logout link rendered by the role, never `page.goto(LOGOUT_URL)`.
The same rule applies to login, password change, account deletion, file upload, post submission, and every other user-initiated action.

Resolution order for the logout step specifically:

1. Click a logout control rendered on the role's currently authenticated surface (link or button whose accessible name matches `logout` / `sign out` / `sign-out` / `abmelden`).
2. If the logout control sits behind a user / account menu, click the menu trigger first, then click the logout control inside it.

The universal-logout service ([web-svc-logout](../../../../../roles/web-svc-logout/)), when attached to a deployment, injects JavaScript that auto-detects every logout control across the role tree and rewrites it to redirect through Keycloak's end-session endpoint.
Persona scenarios therefore do NOT branch on whether universal-logout is active: they always click the role's own logout button.
The injected JS handles the redirect when active, the click clears the local session when not, and the post-click assertion (`assertUnauthenticatedLanding`) is identical in both cases.

If neither step finds a logout control, the test MUST fail.
The role's authenticated surface MUST expose an in-app logout button; navigating to a logout URL as a workaround is forbidden.

`page.goto` is only permitted to put the browser on the next surface (open the dashboard, open a protected URL to trigger an auth redirect, etc.); it MUST NOT be used to *invoke* an action that the UI exposes as a click target.

`page.context().clearCookies()` is permitted only as a final cleanup AFTER a click attempt and only when the click chain itself could not produce a verifiable logged-out state.

## Per-service assertion catalogue 🚦

What "exercise the service" means at each gate inside the persona flows.
Non-exhaustive; new services inherit the same shape (real end-to-end check that fails when the integration breaks, gated via `skipUnlessServiceEnabled`).

| Service | Assertion at the gate |
| --- | --- |
| `dashboard` | The consumer role's spec does NOT exercise the dashboard tile. `web-app-dashboard/files/playwright/playwright.spec.js` parameterises one tile-reachability test per consumer over `DASHBOARD_TARGET_ROLES_JSON` and delegates the body to `runDashboardCardScenario(page, context, target)` from the sibling `dashboard-card-flow.js` SPOT (tile visibility, click → `#main iframe` embed, header "Tab" button → new browser tab). Consumer specs MUST NOT reimplement any tile / iframe / tab assertions. |
| `oidc` | Visit protected URL, assert redirect to Keycloak's `openid-connect/auth`, log in, assert redirect back, assert authenticated UI. |
| `ldap` | LDAP-bind path. MUST exercise admin AND `biber`. |
| `oauth2` | Protected path triggers oauth2-proxy → Keycloak → callback; `/oauth2/sign_out` re-engages the gate. |
| `email` | Send / receive via the role's mail surface, OR verify rendered notification body via the test mailbox. |
| `logout` | Universal-logout endpoint clears role + SSO session; next protected request re-engages auth. |
| `matomo` | The consumer role asserts only that the matomo tracking snippet is in the HTML and that navigation generates the expected `/matomo.php` request (covered by `assertCspInjections` in the persona-helper). Matomo admin-reach, biber denial, and per-consumer tracker-site registration live in `web-app-matomo/files/playwright/playwright.spec.js` only. |
| `prometheus` | The consumer role asserts only that `/metrics` is reachable at the documented path (where applicable). Prometheus admin-reach, biber denial, and per-consumer `up=1` verification live in `web-app-prometheus/files/playwright/playwright.spec.js` only, parameterised over `PROMETHEUS_TARGET_ROLES_JSON`. |
| CSP / injectors | When any injector service (`asset`, `cdn`, `css`, `javascript`, `simpleicons`, `matomo`) is enabled, the role's `Content-Security-Policy` header MUST list the injector's host. The shared module `personas/utils/csp.js` exposes the full CSP test surface: `assertCspInjections` for the per-injector parity check, `assertCspResponseHeader` and `assertCspMetaParity` for header / meta validation, plus `installCspViolationObserver` / `readCspViolations` / `expectNoCspViolations` for the runtime `securitypolicyviolation` stream. Specs require these helpers from `./personas`. |
| `discourse` | WordPress to Discourse post round-trip and analogous role-pair flows. |
| Static assets (`simpleicons`, `cdn`, `css`, `javascript`, `asset`) | The role's HTML references the expected asset host AND a request returns < 400 with the right content-type. |
| DB engines (`redis`, `mariadb`, `postgres`) | Default: `# nocheck: playwright-service-flag`. Covered by role-local integration tests. Exception: roles that surface DB health in the UI. |
| Sub-components (`coturn`, `collabora`, `onlyoffice`, `talk`, `greenlight`, `ollama`, `webmail`, `webdav`, `imap`, `smtp`, `antispam`, `antivirus`, `oletools`, `fetchmail`, `front`, `resolver`, `admin`, `worker`, `view`, `web`) | Real scenario where the component is the surface, OR `# nocheck: playwright-service-flag` with a pointer to the role-local test that covers it. |
| `<role-name itself>` | Self-provider entries. MUST be `# nocheck: playwright-service-flag` per the "no self-gate" rule. |

## Triggers: when to add or update a scenario ✍️

- Whenever role-local `style.css` or `javascript.js` changes user-visible behaviour, the spec MUST assert on the visible effect.
- Whenever the role enables an auth integration (OIDC, oauth2, LDAP), at least one persona's flow MUST exercise the integrated login path (not only a local-form login).
- When the application supports peer-to-peer messaging, the spec MUST cover a bi-directional `biber` ↔ `administrator` exchange (each delivery asserted in the recipient's inbox from an isolated browser context).
- Every `web-app-*` role MUST include a baseline scenario asserting that the canonical-domain front page emits a `Content-Security-Policy` response header.
  Roles whose surface is API-only or federation-only (no HTML output) MAY skip this and document the omission in the role's `README.md`.
- Cross-role round-trip scenarios (WordPress → Discourse, Bluesky → Mastodon, etc.) live in the spec of the role that **initiates** the action.
  The receiving role asserts the delivery via REST API or DB-bound integration tests, never via its own Playwright spec.
- When `meta/variants.yml` declares variant-specific behaviour (WordPress Multisite, Moodle LDAP-only, …), the spec MAY add scenarios that gate on a variant-specific env var via `test.skip(!process.env.<VARIANT>_ENABLED, "<reason naming the variant flag>")`.
  Variant-gated scenarios MUST surface in the reporter as `skipped` with a reason naming the flag, never as silent no-ops.
- Existing scenarios MUST NOT be deleted when "optimising" a spec.
  Rewrite them to satisfy the rules above or strengthen assertions; do not shrink coverage.
  Deletions are only acceptable when the underlying behaviour was removed from the role itself.

## Selectors and waits ⏳

- Selectors MUST prefer accessible roles, form-scoped buttons, and other stable hooks over brittle DOM lookups or generic labels that can match unrelated UI (e.g. topbar search vs. login submit).
- Waits MUST target meaningful page state (visible elements, URL changes, attached locators).
  Fixed sleeps MUST NOT be used where an explicit wait is available.
- When a flow runs inside an iframe and login or OIDC clicks can reload it, the spec MUST treat the reload as a navigation event: await the next visible state or the new iframe URL, then reacquire the frame and rebuild locators before the next interaction.
  A stale iframe handle MUST NOT be reused across redirects.

### Test-budget overrides ⏱️

The Playwright per-test default of 30 s is too tight for several flows.
Use `test.setTimeout(<ms>)` at the top of the test body (after the gates) and document the reason in a comment when the scenario includes any of:

- An OIDC round-trip plus admin token request (allow ≥ 60 s).
- Email delivery via Mailu / external SMTP (allow ≥ 60 s for the first inbox poll, ≥ 600 s for full P2P round-trips that wait for matterbot, antivirus scan, etc.).
- Federation propagation across two services (variable; budget per-flow but log the chosen number).
- Any cross-role round-trip (e.g. WordPress → Discourse): allow ≥ 300 s for the body and any teardown that runs in the test's `finally`.

The chosen budget MUST be visible in a comment on the same line as `test.setTimeout`, naming the slowest sub-step it covers, so future readers can adjust it without re-deriving.

### Cleanup and teardown 🧹

Scenarios that create persistent state (WordPress posts, Discourse topics, Keycloak group memberships, file uploads, …) MUST clean up in a `try { ... } finally { ... }` block.
The teardown MUST:

- Run regardless of body outcome (success, assertion failure, exception).
- Be idempotent (re-running the same cleanup MUST NOT error: a second delete on an already-gone resource MUST be a no-op).
- Carry its own bounded timeout (`Promise.race` against an explicit deadline) so a hung delete request cannot consume the whole test budget.
- NOT mask the original test failure: log cleanup errors via `console.warn` rather than throwing, and let the body's assertion failure surface.

## Environment contract 🔌

- Every env variable the spec reads MUST be exposed in the role's `templates/playwright.env.j2`.
  Names MUST match exactly.
- URLs, domains, and credentials MUST come from the rendered `.env`.
  No hardcoded values in the spec.
- The minimum env set for any spec following the persona flows is `APP_BASE_URL`, `CANONICAL_DOMAIN`, and `LOGOUT_URL`.
  `DASHBOARD_BASE_URL` is rendered only by the dashboard role's own spec, because consumer personas enter at `APP_BASE_URL` directly.
  Specs that gate on auth additionally read at least one of `OIDC_ISSUER_URL`, `KEYCLOAK_BASE_URL`, plus the persona credentials `ADMIN_USERNAME` / `ADMIN_PASSWORD` and `BIBER_USERNAME` / `BIBER_PASSWORD`.
  Specs that exercise integrations (Matomo, Discourse, Email, Prometheus, …) read the integration-specific keys defined in [Agent `playwright.env.j2`](../../../../agents/files/role/playwright.env.j2.md).
- `docker --env-file` preserves the quotes emitted by the `dotenv_quote` Jinja filter.
  Specs MUST decode quoted values before building URLs or typing credentials.
  The recurring helpers `decodeDotenvQuotedValue(value)` and `normalizeBaseUrl(value)` live in [`personas/utils/dotenv.js`](../../../../../roles/test-e2e-playwright/files/personas/utils/dotenv.js) and are re-exported through `require("./personas")`.
  Specs that need them MUST import from `./personas`; inline copies are forbidden and caught at review.

## Service gating contract 🔒

- All `<NAME>_SERVICE_ENABLED` reads go through the `service-gating.js` helper, never `process.env` directly.
- The helper hard-fails on unknown service names.
  Adding a new gate requires both the env-template flag and at least one `skipUnlessServiceEnabled('<svc>')` call in the spec; the parity guards [test_env_services_match.py](../../../../../tests/integration/roles/playwright/test_env_services_match.py) and [test_spec_env_gates.py](../../../../../tests/integration/roles/playwright/test_spec_env_gates.py) enforce that contract.

## Final state ✅

- Every scenario MUST end with the browser in a clearly logged-out state.
- The browser console MUST be clean of errors when the flow depends on injected JavaScript.
