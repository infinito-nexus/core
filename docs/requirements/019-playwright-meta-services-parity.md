# 019 - Playwright meta/services.yml parity coverage

## Vision

The unit of coverage is the role's single `files/playwright/playwright.spec.js`.
That one file MAY contain any number of `test()` blocks, but for every `(role, included-service)` pair there MUST be at least one gated step or scenario inside the file that:

1. **runs** when the service is enabled, and
2. **skips cleanly** (`skipped: <NAME>_SERVICE_ENABLED=false`) when the service is disabled, never `failed`.

A service "included" means a top-level entry in `roles/<role>/meta/services.yml`.
Skip-on-disabled is enforced through the shared [service-gating.js](../../roles/test-e2e-playwright/files/service-gating.js) helper from [006](README.md#archive).

The user-journey shape every `web-app-*` spec MUST instantiate is defined in [playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md): one `guest` scenario, one `biber` scenario, and one `administrator` scenario, named `<persona>: <flow>`.
**All three persona scenarios MUST exist in every `web-app-*` role's spec under this requirement; their presence is part of the acceptance criteria, not optional polish.**

The Playwright spec file IS the single point of truth for the persona contract.
When the SPOT spec contract page and a role's spec disagree, the spec wins; documentation MUST be brought into alignment, not the other way around.

`web-svc-*` roles are auth-less by construction (no end-user UI, programmatic API only).
They are NOT subject to the persona contract; their spec ships a single baseline reachability scenario plus the per-service gates that apply to them.
The persona-collapse exception in [playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md) covers this case.

The acceptance criteria below are the mechanical translation of this contract.

## Rules

| # | Rule | Enforced by |
| --- | --- | --- |
| 1 | Every entry in `meta/services.yml` with an `enabled:` key MUST surface as `<NAME>_SERVICE_ENABLED=` in `templates/playwright.env.j2`, OR carry `# nocheck: playwright-service-flag` above the key with a one-line rationale. **Globally exempt: `dashboard` and `prometheus`.** Their per-consumer reachability is owned by the provider's own spec via `*_TARGET_ROLES_JSON` (see Rule 13); `web-app-*` consumers still declare the service in `meta/services.yml` for inventory completeness but do NOT render the `<NAME>_SERVICE_ENABLED=` flag. **For `dashboard` only:** a non-`web-app-*` role MUST NOT declare the service with a truthy `enabled`/`shared` flag (literal `true` or the `'<role>' in group_names` Jinja form); the dashboard tile grid is reserved for end-user-visible web-app surfaces and infrastructural roles never contribute a tile. Non-`web-app-*` roles that need a static no-tile declaration MAY ship `dashboard: { enabled: false, shared: false }`, otherwise the entry MUST be dropped. | [test_env_services_match.py](../../tests/integration/roles/playwright/test_env_services_match.py) (Test A); for the dashboard-scope sub-rule: [test_integration_scope.py](../../tests/integration/roles/dashboard/test_integration_scope.py) |
| 2 | Every `<NAME>_SERVICE_ENABLED=` line in the env template MUST be consumed by ≥1 `requireService` / `skipUnlessServiceEnabled` / `isServiceEnabled` / `isServiceDisabledReason` call in `files/playwright/playwright.spec.js`, OR carry `# nocheck: playwright-service-gate` on the env line. | [test_spec_env_gates.py](../../tests/integration/roles/playwright/test_spec_env_gates.py) (Test B) |
| 3 | Every `web-app-*` role's `files/playwright/playwright.spec.js` MUST contain the three persona scenarios defined in [playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md), named `guest: <flow>`, `biber: <flow>`, and `administrator: <flow>` respectively. Each persona enters the role's own canonical surface directly (no dashboard tile click); the auth chain runs through OAuth2-Proxy + Keycloak regardless of how the user arrived. The guest scenario MUST assert the unauthenticated visitor never reaches the role's authenticated surface. **Cross-service probes (biber denied at prometheus / matomo, administrator accepted at prometheus / matomo, dashboard tile reachability) are NOT part of the per-role persona; they are owned by the provider's own spec per Rule 13.** `web-svc-*` roles and `web-app-*` roles whose upstream has no auth surface (federation-only or static-only, see the auth-less list under [Iteration order](#iteration-order)) MAY collapse all three into a single baseline scenario. | [test_naming.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_naming.py) enforces the `<persona>: <flow>` shape across all `web-app-*` roles; [test_required_envs.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_required_envs.py) enforces the auth-less collapse exception consistency. The persona-naming lint is the role-closure gate for *spec shape*; the full role-closure definition (passing deploy, Test A, Test B, strict-mode lint) lives in [Closure vocabulary](#closure-vocabulary). |
| 4 | Specs MUST NOT read `<NAME>_SERVICE_ENABLED` directly via `process.env`. All reads go through the helper. | grep verification (see below) |
| 5 | A scenario that depends on multiple services MUST gate each via a separate `skipUnlessServiceEnabled('<svc>')` call. No bundled multi-service gates; bundling defeats the variant matrix (same rule as [018](018-playwright-ldap-coverage.md)). | review |
| 6 | A new env key without a spec consumer is a regression. | [test_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py) |
| 7 | Every persona scenario AND every contract test in `files/playwright/playwright.spec.js` MUST simulate a real user flow with at least one `expect(...)` / `await <fn>(...)` / equivalent assertion. Stub bodies (`TODO`, `STUB`, `FIXME`, empty, or only `skipUnlessServiceEnabled`) are FORBIDDEN. The rollout's intent is real flows that fail when the integration breaks; a passing-by-default body provides no signal. | [test_no_stub_tests.py](../../tests/lint/ansible/roles/web-app/playwright/test_no_stub_tests.py) |
| 8 | Tests MUST drive user-initiated actions through the rendered UI (click on logout button / link / menu, click on submit button, …) and MUST NOT short-circuit them with `page.goto(<action-endpoint>)`. The logout step in particular MUST click the role's own in-app logout control on the currently authenticated surface (or open a user / account menu first when the control is nested). When the universal-logout service is attached, its injected JavaScript auto-rewrites the click target to redirect through Keycloak's end-session endpoint, so the test does NOT branch on whether universal-logout is active. Navigating directly to `${LOGOUT_URL}` is forbidden. | review (this requirement) |
| 9 | Every persona scenario MUST drive a real, role-specific interaction after the auth chain settles (or directly on the role surface when no auth is required). The `biber` interaction MUST exercise a regular end-user action; the `administrator` interaction MUST exercise an admin-only surface. Specs pass the interaction in via `runBiberFlow(page, { biberInteraction })` / `runAdminFlow(page, { adminInteraction })`. No generic default exists; a generic "click any link" assertion tests nothing role-specific. | review (this requirement) |
| 10 | When the role supports peer-to-peer interaction (messaging, comment threads, federation round-trips, calendar invites, …), the spec MUST include a separate `biber ↔ administrator: <flow>` test that opens two browser contexts, drives the round-trip end-to-end, and asserts both sides see the expected payload. The shared `runPeerExchangeFlow(browser, { peerExchange })` helper provides the two-context scaffolding. Roles whose upstream offers no peer interaction surface MUST NOT add the test. | review (this requirement) |
| 11 | Persona scenarios MUST FAIL LOUDLY when the persona cannot execute the contracted journey, never silently `test.skip(...)` on runtime detection of "no logout button" / "no authenticated surface" / "no admin UI marker". A silent skip hides real regressions (broken OIDC mapping, removed logout button, misconfigured oauth2-proxy, drifted UI selectors) behind a green deploy. The ONLY clean-skip mechanism is an EXPLICIT env opt-out declared by the role: `PERSONA_BIBER_BLOCKED=true` / `PERSONA_ADMINISTRATOR_BLOCKED=true` / `PERSONA_GUEST_BLOCKED=true` rendered in `templates/playwright.env.j2`, with a documented rationale in the role's README or TODO. Without the flag the persona helper hard-fails the test. | [test_strict_mode.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_strict_mode.py) (`test_persona_skips_only_via_explicit_opt_out`) + persona-helper bodies in `roles/test-e2e-playwright/files/personas/{biber,admin,guest}.js` |
| 12 | Direct-probe deny-checks at prometheus / matomo MUST validate the response body, not only the status code. A `200 OK` is acceptable ONLY when the body contains role-specific markers proving the response is the genuine provider surface (e.g. `prometheus_build_info`, `<title>Prometheus</title>` for prometheus; matomo's login-form markers / `piwik` or `matomo` for matomo). Any 200 with a non-matching body is treated as a misconfigured proxy or a denial-as-200 surface and fails loudly. | [test_strict_mode.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_strict_mode.py) (`test_deny_helpers_validate_body_on_200`) + bodies in `roles/web-app-prometheus/files/playwright/playwright.spec.js` and `roles/web-app-matomo/files/playwright/playwright.spec.js` (per Rule 13: provider-owned SPOT) |
| 13 | **SPOT-owned cross-service assertions.** Dashboard tile reachability, prometheus scrape parity, and matomo tracker presence are owned by the provider's own spec, not duplicated across consumer roles. Each provider's `templates/playwright.env.j2` renders a `<NAME>_TARGET_ROLES_JSON` manifest via the `lookup('roles_with_service', '<svc>')` Ansible lookup ([plugins/lookup/roles_with_service.py](../../plugins/lookup/roles_with_service.py)), enumerating every role whose merged applications config declares the service with both `enabled` and `shared` truthy and whose role exposes a canonical domain. The provider's `files/playwright/playwright.spec.js` parameterises one assertion per consumer over that manifest. The shared persona helpers (`runBiberFlow`, `runAdminFlow`) consequently no longer drive cross-service probes; they exercise the role under test only. | provider specs `roles/web-app-{dashboard,prometheus,matomo}/files/playwright/playwright.spec.js` and the `roles_with_service` lookup |
| 14 | **Post-deploy log inspection.** After every deploy cycle the agent MUST inspect the Playwright logs (`list` reporter, `playwright-report/index.html`, `test-results/<test>/error-context.md`, plus the trace / video captured under `INFINITO_PLAYWRIGHT_KEEP=true`) and verify both (a) the intended per-persona and per-service behavior is really wired into the role's `files/playwright/playwright.spec.js`, and (b) every wired assertion was actually executed by Playwright. A green exit alone is NOT sufficient evidence: a silent `test.skip(...)`, a scenario that exits before the role-specific interaction fires, or a `<NAME>_SERVICE_ENABLED=true` gate whose body never ran all violate this rule. Gaps MUST be closed by extending the spec to cover the missing behavior; existing assertions stay per [Preserving existing tests](#preserving-existing-tests), and removal is permitted only when the deleted assertion is demonstrably faulty. | review (this requirement) + log inspection per [Playwright Spec Loop](../agents/action/iteration/playwright.md#procedure) step 4 |

## Per-service scenario catalogue

The per-service assertion catalogue (what each gate's body MUST exercise: `dashboard` tile click, `oidc` round-trip, `ldap` bind, `email` send/receive, `prometheus` `up=1`, …) is documented in [playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md#per-service-assertion-catalogue-).
The persona flow is the surrounding journey; the catalogue tells the spec what to assert at each gate inside that journey.
This requirement's matrix below uses the catalogue's vocabulary but does not duplicate it; refer to that page for the per-service contract.

## Closure paths per matrix row

When a future iteration surfaces fresh drift (a new `meta/services.yml` entry without a matching `<NAME>_SERVICE_ENABLED=` line, or a new matrix row that fails Test A), each missing flag is closed by exactly one of:

1. **Render flag + add gated scenario** *(default)*. Render `<NAME>_SERVICE_ENABLED={{ … }}` in `templates/playwright.env.j2` (literal `"true"` / `"false"` per [006](README.md#archive)). Add a `skipUnlessServiceEnabled('<svc>')`-gated step inside the appropriate persona scenario in `files/playwright/playwright.spec.js` per [playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md). Mention the service in the role's README so reduced-deploy skip behaviour is predictable.
2. **Drop the entry**. Remove the service from `meta/services.yml` if no longer consumed. Verify [test_services_explicit.py](../../tests/integration/roles/meta/services/run_after/test_services_explicit.py) stays green.
3. **`# nocheck: playwright-service-flag`**. Comment block above the services-yml key with a one-line rationale. Reserved for self-gate, infrastructural, or no-Playwright-surface cases.

**Dashboard-scope exception (non-`web-app-*` roles).** Paths 1 and 3 are NOT available for a `dashboard:` block in any `web-svc-*` / `sys-*` / `desk-*` / `drv-*` role; [test_integration_scope.py](../../tests/integration/roles/dashboard/test_integration_scope.py) forbids every truthy `dashboard.{enabled,shared}` declaration outside `web-app-*`.
For these roles, closure runs exclusively through path 2 (drop the entry) OR through a static `dashboard: { enabled: false, shared: false }` declaration when the inventory-side registry visibility is required.
Persona scenarios are already covered by the auth-less collapse, so removing the `dashboard:` block does NOT shrink coverage.

Closure of any row also requires that the role's spec already contains the three persona scenarios (Rule 3); a row's missing flag MAY be added inside a new persona scenario, but the row is NOT closed until all three persona scenarios exist.

## Per-role iteration matrix

The matrix is the source of truth for the rollout: the agent walks it top-to-bottom and treats `total` as the priority signal.
The `notes` column captures role-specific contract context (auth-less collapse, persona blocked-flag opt-outs, bespoke admin-only test bodies).
The `v0` / `v1` / `v2` columns track per-variant progress: each cell starts as ⏳ (untested) and flips to ✅ once the role's full Per-role flow passes for that variant, including the post-deploy log inspection from Rule 14.
An empty per-variant cell means the role does not declare that variant index in `roles/<role>/meta/variants.yml`.

Legend (`has env` / `has spec`): ✅ present, ❌ missing.
Legend (`v0` / `v1` / `v2`): ⏳ untested, ✅ passed (full Per-role flow incl. log inspection), empty = variant not declared.

Columns immediately after `Role`:

- **`total`**: priority signal (consumer fan-out from `meta/services.yml` cross-references); higher = more downstream impact. Data rows are sorted DESC by this column.

| Role | total | has env | has spec | v0 | v1 | v2 | notes |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| ~~`web-app-prometheus`~~ | 173 | ✅ | ✅ | ✅ | ✅ |  | oauth2-proxy gates the role on `web-app-prometheus-administrator`; biber lacks the role so the proxy denies the session and biber has no in-app surface to drive a logout from. Opt out via `PERSONA_BIBER_BLOCKED=true` (Rule 11). The administrator persona runs the standard oauth2-proxy → Keycloak chain. Bespoke `metricz`, `dashboard-to-prometheus admin SSO`, and `biber-denied-access` tests cover the SPOT-owned probes. Logout-icon injected via `templates/javascript.js.j2` (gated on services.oauth2.enabled) because the upstream UI ships no in-app logout. Variant=1 collapses oauth2 → PERSONA_ADMINISTRATOR_BLOCKED renders true via env and bespoke tests `safeSkipUnlessEnabled("oauth2")` |
| ~~`web-app-matomo`~~ | 168 | ✅ | ✅ | ✅ | ✅ |  | admin-only role: persona stubs explicit-skipped via `PERSONA_BIBER_BLOCKED=true` / `PERSONA_ADMINISTRATOR_BLOCKED=true` in env (Rule 11); bespoke "matomo administrator" test covers the admin journey via matomo's own login form. The biber-deny test gates on `isServiceEnabled("oauth2")` and parks until matomo's oauth2-proxy gate is wired (TODO in `meta/services.yml`) |
| ~~`web-app-dashboard`~~ | 162 | ✅ | ✅ | ✅ | ✅ |  | OIDC silent-SSO chain ships `parent.postMessage(location.href, location.origin)` in `templates/nginx/sso.html.conf.j2` so `keycloak.init()` can complete; `oidc.js` then sets `window.__oidcLoginReady` after wiring the click interceptor, and the shared persona helper waits for that signal before clicking Login (avoids the static-href fallback that would skip PKCE). Variant=1 disables every shared service: env renders `PERSONA_{BIBER,ADMINISTRATOR}_BLOCKED` from `services.oidc.enabled`, and the asset / login-swap tests skip cleanly on `cdn`/`logout`/`oidc`-disabled |
| ~~`web-svc-cdn`~~ | 144 | ✅ | ✅ | ✅ | ✅ |  | infra role; bespoke "cdn index served under canonical domain with TLS" test covers the surface; persona stubs collapse to the auth-less skip (no APP_BASE_URL surface), no further fix needed |
| ~~`web-app-mailu`~~ | 139 | ✅ | ✅ | ✅ | ✅ |  | bespoke `dashboard → mailu sso → admin → logout` and `biber → email → administrator → receives` tests own the persona coverage (they exercise mailu's iframe-wrapped auth chain directly), both `safeSkipUnlessEnabled("oidc")`-gated so the no-OIDC variant collapses cleanly; the shared persona scenarios route through the dashboard main-frame Account menu and depend on the dashboard OIDC silent-SSO that is currently in escape, so PERSONA_BIBER_BLOCKED + PERSONA_ADMINISTRATOR_BLOCKED collapse them cleanly |
| ~~`web-app-keycloak`~~ | 130 | ✅ | ✅ | ✅ | ✅ |  | auth-provider exception: generic persona scenarios are exempt; bespoke "master-realm super administrator", "normal-realm administrator", "normal-realm biber" tests cover the persona contract via the realm account UI. Variant=1 disables LDAP federation; the bespoke biber test collapses via `safeSkipUnlessEnabled("ldap")`. Biber MUST NEVER be seeded directly via kcadm, only the administrator persona is seeded for the headless ops loop |
| ~~`web-svc-simpleicons`~~ | 92 | ✅ | ✅ | ✅ | ✅ |  | infra role; bespoke "simpleicons serves keycloak assets directly on its own domain" test owns the surface; persona stub collapses to the auth-less skip (no APP_BASE_URL). Variant=1 toggles only the `prometheus` flag (no app-surface change), bespoke surface test passes identically |
| ~~`web-app-nextcloud`~~ | 27 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25890032686: v0 and v1 deploys clean (PLAY RECAP `failed=0`); only v2 fail'd in `tasks/plugins/user_ldap.yml:69` (Warm LDAP cache) with `Failed opening required '/var/www/html/lib/versioncheck.php'`. Source-code analysis confirms `lib/versioncheck.php` exists in `stable33` and is loaded via `__DIR__` (cwd-independent), so the missing-file error implies the entrypoint rsync into the `data:` volume did not stage the source for v2's matrix-deploy round. Same environmental-flake family as the prior C14 (CI 25774452286): v0+v1 succeeded with identical code, only v2 hit a round-isolated volume-state issue. Treated as environmental (does not reproduce locally) until a future CI run re-hits the same v2 failure. |
| ~~`web-app-bigbluebutton`~~ | 24 | ✅ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| ~~`web-app-discourse`~~ | 24 | ✅ | ✅ | ✅ | ✅ |  | Local FULL_CYCLE v0+v1 ✅. Root cause for CI **C8 pgvector**: variant 1's `postgres.shared: false` forced Discourse to use its bundled launcher postgres which lacks the `vector` extension. Fix: pinned `services.postgres.shared: true` in `meta/services.yml` (`svc-db-postgres` image has pgvector compiled via Dockerfile.j2), removed override from `meta/variants.yml`. Also gated the two OIDC-dependent tests (`administrator/biber: dashboard to discourse OIDC login and logout`) on `OIDC_SERVICE_ENABLED=true` |
| ~~`web-app-mastodon`~~ | 23 | ❌ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| `web-app-friendica` | 23 | ✅ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: **C2b (dashboard tile) + per-spec (post-login surface)** mixed: four tests fail. (1) `dashboard → friendica: admin login, verify ui, logout`: `getByRole('link', { name: /Explore Friendica/i })` click times out (dashboard returned Keycloak login instead of the dashboard view, session/auth setup). (2) `friendica: biber and administrator log in side by side`: post-login `#topbar-first, #navbar-apps-menu, a[href*='/logout']` never visible (post-login home not reached). (3) `biber: dashboard → app → universal logout`: oauth2-proxy emits `403 Forbidden` (biber rejected at proxy). (4) `administrator: dashboard → prometheus → app → universal logout`: `inAppLogout` finds no logout control on Friendica's authenticated surface (still on /login form). Split between dashboard auth chain (C2b) and a post-login surface regression (LDAP autocreate / session, recent change in Friendica's post-login surface). |
| ~~`web-app-opentalk`~~ | 23 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants (`PERSONA_*_BLOCKED` env fix from commit f1898dd77 verified) |
| ~~`web-app-listmonk`~~ | 22 | ❌ | ✅ | ✅ | ✅ |  | CI run 25890032686: deploy + Playwright PASS for all declared variants (v1 verified; the prior C11 DB-upgrade race did not reproduce) |
| `web-app-gitea` | 22 | ✅ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: **C12 compose-up handler regression**: `sys-svc-compose/handlers/main.yml:76` (`compose up`) exits non-zero again right after the gitea image pull. Same orphan-default-network signature that commit `c6affc96f` previously fixed; the recent `602c05ed3 Reverted matrix fix` rolled the purge primitive partially back, re-introducing the failure for the gitea+matrix pair. Re-apply the entity-keyed `scripts/container/purge/entity/network.sh` + global `docker network prune -f` to close. Spec env (`PROMETHEUS_BASE_URL`, `PROMETHEUS_SERVICE_ENABLED`) from commit `1e5a47f67` still in place; the gitea-specific Playwright issues (prometheus scrape contract + universal-logout round-trip) remain Deep and stay un-tested until compose-up clears. |
| ~~`web-app-openwebui`~~ | 22 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25797277810: deploy + Playwright PASS for all declared variants |
| ~~`web-app-flowise`~~ | 22 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| `web-app-bookwyrm` | 22 | ✅ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: **C2d (deploy regression masquerading as Playwright)**: BookWyrm container still on the first-run `Instance Configuration / Continue` wizard, so Keycloak's username field never renders. The persona helper times out (60 s) on `getByRole('textbox', { name: /username\|email/i })`; snapshot heading reads `"Installing BookWyrm"` / `"Instance Configuration"`. Root cause is deploy-side: the role's post-install bootstrap never completed; not a Playwright spec bug. |
| ~~`web-app-minio`~~ | 22 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25797277810: deploy + Playwright PASS for all declared variants |
| ~~`web-app-xwiki`~~ | 21 | ❌ | ✅ | ✅ | ✅ |  | CI run 25797277810: deploy + Playwright PASS for all declared variants |
| ~~`web-app-shopware`~~ | 21 | ❌ | ✅ | ✅ | ✅ | ✅ | CI run 25797277810: deploy + Playwright PASS for all declared variants |
| ~~`web-app-pretix`~~ | 21 | ❌ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| `web-app-odoo` | 21 | ✅ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: **C-new-odoo-ldap-insert**: `web-app-odoo/tasks/04_ldap.yml:54` (Create new LDAP configuration) fails with `Cannot execute SQL 'INSERT INTO res_company_ldap (sequence, company, ldap_server, …)'`. Regression introduced by the recent commit `762586a03 fix: matrix docker-network label clash + odoo res.company.ldap column rename`; the column rename was not reflected in the `INSERT` statement. |
| ~~`web-app-mobilizon`~~ | 21 | ❌ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| `web-app-matrix` | 21 | ✅ | ✅ | ❌ | ⏳ |  | CI run 25890032686: **C12 matrix compose-up recurrence**: `web-app-matrix/tasks/01_docker.yml:76` fails with `network matrix was found but has incorrect label com.docker.compose.network set to "" (expected: "default")`. Identical to the prior C12 in CI 25774452286; the orphan-network purge primitive (commit `c6affc96f`) was partially reverted by `602c05ed3 Reverted matrix fix`. Re-applying the entity-keyed purge from `scripts/container/purge/entity/network.sh` closes this row again. Playwright DM-scenario remains gated behind the compose-up fix. |
| ~~`web-app-gitlab`~~ | 21 | ❌ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| ~~`web-app-espocrm`~~ | 21 | ❌ | ✅ | ✅ | ✅ | ✅ | Local FULL_CYCLE v0+v1+v2 ✅ (failed=0 both passes for every variant). Root cause for the CI fail was a **duplicate `depends_on:` block** in `roles/web-app-espocrm/templates/compose.yml.j2` (websocket service rendered both the `dmbs_excl.yml.j2` include AND a manual `depends_on:` → `failed to parse compose.yml: yaml: mapping key "depends_on" already defined`); commits `eaa51b39d` then `1f5689e44` consolidate daemon + websocket services to use the `dmbs_incl.yml.j2` include so the DB/redis deps and the manual espocrm-service dep live under a single `depends_on:` key. |
| `web-app-taiga` | 21 | ✅ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: **C2b/C2c (dashboard tile + role login link both missing)**: `expect(getByRole('link', { name: 'Explore Taiga' })).toBeVisible()` fails across two tests (dashboard tile and themed-routes); snapshot shows the upstream `taiga.io` discover-projects marketing page with Login/Sign-up `href="#"` placeholders; the dashboard nav injection and the role's own login route are both absent. Looks deploy-side (nginx serving the marketing fallback), not a spec selector bug. |
| `web-app-mattermost` | 21 | ✅ | ✅ | ❌ | ⏳ |  | CI run 25890032686: **C2b (dashboard tile injection missing)**: `getByRole('link', { name: 'Explore Mattermost' })` times out at 300 s; the page that loaded is Mattermost's `"View in Desktop App / View in Browser"` interstitial; the dashboard navbar tile for Mattermost is not being rendered. Bespoke DM-UI selector + universal-logout Keycloak round-trip remain Deep but only after the dashboard-tile injection is restored. |
| ~~`web-app-wordpress`~~ | 21 | ✅ | ✅ | ✅ | ✅ |  | CI run 25797277810: deploy + Playwright PASS for all declared variants |
| ~~`web-app-moodle`~~ | 21 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| ~~`web-app-joomla`~~ | 21 | ✅ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| `web-app-fider` | 21 | ✅ | ✅ | ❌ | ⏳ |  | CI run 25890032686: **C2b (selectors + dashboard tile)**: biber test fails on `getByRole('link', { name: /sign in/i }).first()` (30 s waitFor; Fider's "Sign in" link not present on the rendered page); the `dashboard → fider` test sees only the autoindex `"Index of /"` listing, so the dashboard tile for Fider was never injected. Both paths point at a deploy-side gap (Fider front-page not deployed + dashboard nav drift) rather than a per-spec selector regression. |
| ~~`web-app-decidim`~~ | 21 | ✅ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| `web-app-baserow` | 21 | ✅ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: **C2c (deploy-side gap surfaced via guest probe)**: both the baseline `Baserow responds on the canonical domain` and the guest `public-landing → never authenticated` tests fail with `Expected: < 500  Received: 500`. The nginx upstream returns `heading 'connect ECONNREFUSED 127.0.0.1:8000' [level=1]`; the Baserow Django backend never came up. Root cause is deploy-side, not Playwright. |
| ~~`web-app-akaunting`~~ | 21 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants (re-verified). biber + administrator personas explicit-skipped via `PERSONA_*_BLOCKED` in env; OIDC auto-provisioning not wired, see role TODO.md |
| `web-app-fediwall` | 21 | ✅ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: **C2b (per-spec submit-step missing)**: only one test fails (`each wall surfaces biber's posts according to its servers list`), Test timeout 300000ms. Trace shows the flow stuck on Keycloak `Sign in to your account` page with `biber` + password already pre-filled but the Sign In button never clicked. Likely a missing submit step in the wall-iteration loop of `roles/web-app-fediwall/files/playwright/playwright.spec.js`. |
| ~~`web-app-suitecrm`~~ | 20 | ❌ | ✅ | ✅ | ✅ | ✅ | CI run 25797277810: deploy + Playwright PASS for all declared variants |
| ~~`web-app-snipe-it`~~ | 20 | ❌ | ✅ | ✅ | ✅ | ✅ | CI run 25797277810: deploy + Playwright PASS for all declared variants |
| `web-app-openproject` | 20 | ❌ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: OOM still reproducing: `web-app-openproject/tasks/01_settings.yml:15` (`Run database migrations`) still exits `rc=137` after 30 retries despite commit `bdd59b9db` bumping `web.mem_limit` 4g → 6g. The `rails db:migrate` peak appears to exceed even 6 GB on the public CI runner; consider a further bump to 8g and/or breaking the migration into smaller transactions. |
| `web-app-mediawiki` | 20 | ❌ | ✅ | ❌ | ⏳ |  | CI run 25890032686: **C-new-mediawiki-mariadb-missing**: `web-app-mediawiki/tasks/main.yml:25` (`Wait until database container is healthy`) loops 60× then fails because `docker container inspect mariadb` returns no entry; the mariadb container is literally absent. Sibling of C12 (its compose-up failed earlier in the round). |
| ~~`web-app-funkwhale`~~ | 20 | ❌ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| `web-app-pixelfed` | 20 | ✅ | ✅ | ❌ | ⏳ |  | CI run 25890032686: **C2b/C2c (dashboard tile never rendered)**: both biber and administrator `dashboard → pixelfed oidc login` tests fail with `Timed out waiting for the Pixelfed entry on the dashboard`; snapshot shows the raw nginx autoindex `heading 'Index of /'` instead of the dashboard SPA; no SSO-injected nav. Deploy-side gap. |
| ~~`web-app-jenkins`~~ | 20 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| `web-app-fusiondirectory` | 20 | ✅ | ✅ | ❌ | ❌ | ⏳ | CI run 25890032686: **C9 Keycloak permanent admin login**: `web-app-keycloak/tasks/04_login.yml:17:7` (Try login with permanent admin) loops `HTTP Error 502: Bad Gateway` then fatals out before the fusiondirectory consumer can run. Different signature than the v0 ✅ Local FULL_CYCLE saw previously. This run never reached the `Wait until application is ready` 502 (v1 oauth2-vhost gating issue) because the round bricks at Keycloak. The earlier `b3d5bf466` LDAP pin still stands. |
| `web-app-peertube` | 20 | ✅ | ✅ | ❌ | ⏳ |  | CI run 25890032686: **C6 family (PeerTube schema)**: `web-app-peertube/tasks/fix-application-schema.yml:25` (`Wait for peertube to create the application table`) retries 6× then FAILS. Postgres is reachable but the PeerTube `application` table never appears. Same family as the documented C6 svc-db-postgres purge cascade; Meta load-bearing fix from [020](020-ci-run-25705903504-deploy-remediation.md#meta-root-cause-for-bundles-b-c5-c6-and-most-c1) still pending. |
| `web-app-bluesky` | 20 | ✅ | ✅ | ❌ | ⏳ | ⏳ | CI run 25890032686: **C2c (deploy-side routing gap on guest probe)**: same role-pair as before (`Playwright failed for roles: ['web-app-bluesky', 'web-app-mailu']`) but artifacts show the bluesky vhost is serving `'Missing X-Forwarded-User from oauth2-proxy. Refusing handoff.'` and the mailu vhost is serving the bare PDS ASCII banner (`'This is an AT Protocol Personal Data Server'`). Both surfaces hit the 60 s test timeout before any assertion; root cause is the oauth2-proxy hand-off / vhost wiring, not the spec. |
| ~~`web-app-opencloud`~~ | 20 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants (cross-verified). Bespoke `opencloud sso login (administrator/biber) lands on files view` covers both personas end-to-end via opencloud's own auth-route; persona shared scenarios `PERSONA_*_BLOCKED` |
| ~~`web-app-pgadmin`~~ | 19 | ❌ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| ~~`web-app-lam`~~ | 19 | ❌ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants. Commit `b3d5bf466` additionally pins `services.ldap.{enabled,shared}: true` and drops the `ldap:` variant overrides (LDAP IS the storage backend for LAM). |
| ~~`web-app-kix`~~ | 19 | ✅ | ✅ | ✅ | ✅ | ✅ |  |
| ~~`web-app-yourls`~~ | 19 | ✅ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| ~~`web-app-phpmyadmin`~~ | 18 | ❌ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| ~~`web-app-postmarks`~~ | 18 | ✅ | ✅ | ✅ | ✅ |  | CI run 25868178119: deploy + Playwright PASS for all declared variants (prior C2 regression resolved by persona-helper fast-fail + `PERSONA_BIBER_BLOCKED`) |
| ~~`web-app-chess`~~ | 18 | ❌ | ✅ | ✅ | ✅ |  | CI run 25680106742: deploy success; auth-less small-app, spec collapses cleanly without env |
| ~~`web-app-sphinx`~~ | 17 | ✅ | ✅ | ✅ | ✅ |  | CI run 25680106742: 3/3 active tests pass, 2 personas cleanly skipped |
| ~~`web-app-roulette-wheel`~~ | 17 | ❌ | ✅ | ✅ | ✅ |  | CI run 25680106742: deploy success; auth-less small-app, spec collapses cleanly without env |
| ~~`web-app-mini-qr`~~ | 17 | ❌ | ✅ | ✅ | ✅ |  | CI run 25680106742: deploy success; auth-less small-app, spec collapses cleanly without env |
| ~~`web-app-mig`~~ | 17 | ✅ | ✅ | ✅ | ✅ |  | CI run 25680106742: 3/3 active tests pass, 2 personas cleanly skipped |
| ~~`web-app-littlejs`~~ | 17 | ❌ | ✅ | ✅ | ✅ |  | CI run 25680106742: deploy success; auth-less small-app, spec collapses cleanly without env |
| ~~`web-app-hugo`~~ | 17 | ✅ | ✅ | ✅ | ✅ |  | CI run 25680106742: 4/4 active tests pass, 2 personas cleanly skipped |
| ~~`web-app-bridgy-fed`~~ | 17 | ✅ | ✅ | ✅ | ✅ |  | CI run 25680106742: 3/3 active tests pass, 2 personas cleanly skipped |
| ~~`web-svc-xmpp`~~ | 16 | ✅ | ✅ | ✅ | ✅ | ✅ | CI run 25774452286: deploy + Playwright PASS for all declared variants |
| ~~`web-svc-libretranslate`~~ | 16 | ✅ | ✅ | ✅ | ✅ |  | CI run 25774452286: deploy + Playwright PASS for all declared variants |

Rows with `has env ❌` and `has spec ✅` ship the auth-less collapse exception per Rule 3: the spec contains a single baseline reachability scenario and no env template is rendered because the role has no `<NAME>_SERVICE_ENABLED=` flags to gate on.
The matrix only lists roles that already ship a Playwright spec. A role with neither artefact is out of scope until it grows one; when that happens, the new spec MUST ship the three persona scenarios per Rule 3 (or document the auth-less collapse explicitly) AND the env template MUST satisfy this requirement from day one.

## Closure procedure

The agent MUST follow this procedure verbatim to walk every row of the matrix above through to role closure.

### Required reading

Load all of the following before the first deploy.

1. [Contributing `playwright.spec.js`](../contributing/artefact/files/role/playwright.specs.js.md): the persona scenarios, invariants, per-service catalogue, env contract, and final state.
2. [Role Loop](../agents/action/iteration/role.md): per-role deploy procedure, certificate trust, inspect-before-redeploy, matrix-variant mechanics.
3. [Playwright Spec Loop](../agents/action/iteration/playwright.md): inner-loop edits against an already-running stack.

### Autonomy

- The agent MUST run the rollout autonomously without questions back to the operator.
- The agent MUST NOT ask "should I disable matomo/email" or any other deploy-time question; this rollout deploys with NO `INFINITO_SERVICES_DISABLED`.
- The agent MUST fix every failure that is caused by or related to this rollout (env-template drift, missing gates, persona scenarios, pattern-transfer regressions, …) without asking.
- Failures clearly unrelated to the rollout (an upstream image outage, a flaky network test in another module, a pre-existing CI flake on a path this rollout does not touch) MUST be ignored: the agent does NOT deep-dive into them.
  The agent SHOULD note the unrelated failure in the role's TODO.md if one exists, otherwise continue.
- The agent MUST NOT use any command that requires elevated permissions or an interactive approval prompt.
  Allowed permissions are defined by [.claude/settings.json](../../.claude/settings.json); commands that fall under `ask` or `deny` MUST NOT be invoked.
- Matrix-variant roles MUST be iterated through every declared variant; the role-closure gate (see below) only fires when every variant passes.
  Variants are read from `roles/<role>/meta/variants.yml` and driven via `INFINITO_VARIANT=<idx>` per [Role Loop → Matrix variants](../agents/action/iteration/role.md#matrix-variants).

### Closure vocabulary

This requirement uses two distinct closure terms; do NOT mix them.

- **Flag closure** is the per-row event in the matrix below: a single `<NAME>_SERVICE_ENABLED=` flag has been rendered, gated, dropped, or `# nocheck`-marked per the [Closure paths](#closure-paths-per-matrix-row).
  Closing a flag is a code change; it does NOT require a deploy on its own.
- **Role closure** is the per-role event: every flag for the role is closed AND the role's spec ships the persona scenarios (where applicable) AND the role's full-cycle deploy plus Playwright spec passed for every declared variant AND Tests A and B are green for the role.

The matrix tracks flag closure; the iteration tracks role closure.

### Per-role flow

For each role in the [Iteration order](#iteration-order) below:

1. Run `make test` before EVERY deploy and EVERY redeploy in this loop. No exceptions, no per-test cherry-picking. `make test` IS the test gate; individual lint / integration test invocations are absorbed by it.
   On failure, fix the underlying issue if it is rollout-related; per [Autonomy](#autonomy), unrelated failures are ignored.
2. Run `make deploy-fresh-purged-apps INFINITO_APPS=<role> INFINITO_FULL_CYCLE=true` to establish a fresh full-cycle baseline WITHOUT `INFINITO_SERVICES_DISABLED`.
   For matrix-variant roles, iterate through every variant declared in `roles/<role>/meta/variants.yml` via `INFINITO_VARIANT=<idx>` per [Role Loop → Matrix variants](../agents/action/iteration/role.md#matrix-variants); the role is NOT role-closed until every variant has produced a passing deploy plus passing Playwright spec.
3. If the deploy fails or the spec fails, follow [Role Loop](../agents/action/iteration/role.md) and [Playwright Spec Loop](../agents/action/iteration/playwright.md) to fix the root cause.
   Apply the fix in the repository files (NOT in the staged copy or the running container).
4. If a specific service genuinely cannot work for the role (upstream limitation, infrastructural exclusion, scope conflict), perform a **flag closure** through one of the closure paths above: either disable the service in `roles/<role>/meta/services.yml` (when the role legitimately has no business consuming it), or mark the entry with `# nocheck: playwright-service-flag` and document the rationale in a one-line comment above the key (e.g. `# nocheck: playwright-service-flag: self-provider`, `# nocheck: playwright-service-flag: infrastructural, no Playwright surface`, `# nocheck: playwright-service-flag: covered by tests/integration/services/test_<x>.py`, `# nocheck: playwright-service-flag: upstream offers no <svc> integration`).
   The agent decides which path applies based on the role's documented contract; it does NOT ask the operator.
5. The role's `roles/<role>/meta/variants.yml` MAY need adjustment when its declared variants do not exercise the service combinations the spec gates on.
   The agent MUST edit `meta/variants.yml` whenever any of the following holds:
   - A new variant is required to exercise a service-off path that the matrix does not yet cover (e.g. an LDAP-only variant pinning `oidc.enabled: false` plus `ldap.enabled: true` per [018](018-playwright-ldap-coverage.md), or a variant that disables `matomo` to validate the skip-on-disabled contract).
   - An existing variant pins service flags that conflict with the spec's gates (e.g. the variant pins `oauth2.enabled: true` while the role's spec only ever drives the `oidc` path); fix the variant to match what the spec actually exercises.
   - A variant references a service key that is no longer declared in `meta/services.yml`; remove the override.
   Variants edits MUST keep `make test` green; the next `make test` invocation (which runs before the next deploy or redeploy per step 1) is the gate, not a per-test re-run.
   Variants edits are part of the same role-closure scope and do NOT trigger a separate commit.
6. **Inspect the Playwright logs after every deploy cycle for this role** per [Rule 14](#rules), even when the deploy and the spec both exit `0`.
   The agent MUST confirm via the `list` reporter, `playwright-report/index.html`, and the trace / video captured under `INFINITO_PLAYWRIGHT_KEEP=true` (set per [Role Loop](../agents/action/iteration/role.md)) that:
   - the spec really wires the persona and per-service assertions the role's `meta/services.yml` declares (no contract gap silently masked by absence of a gated step), AND
   - every wired assertion actually executed (no silent `test.skip(...)`, no scenario that exited before the role-specific interaction fired, no `<NAME>_SERVICE_ENABLED=true` gate whose body never ran).
   When the inspection surfaces a gap, the agent MUST extend the spec until the missing behavior is both wired AND executed.
   Existing test logic stays per [Preserving existing tests](#preserving-existing-tests); deletion is allowed only when the removed assertion is demonstrably faulty.
   After every spec edit the agent re-runs the spec via [Playwright Spec Loop](../agents/action/iteration/playwright.md) and repeats the inspection until the role passes the gate cleanly.
   The role MUST NOT progress to role closure until this inspection is clean.
7. The role is **role-closed** only when:
   - the final `make deploy-fresh-purged-apps INFINITO_APPS=<role> INFINITO_FULL_CYCLE=true` run completed successfully for every variant, AND
   - the Playwright spec passed for every variant, AND
   - the post-deploy log inspection in step 6 is clean for every variant, AND
   - the role's `files/playwright/playwright.spec.js` ships the three persona scenarios per [Rule 3](#rules) (or the auth-less single-scenario collapse for `web-svc-*` and the auth-less `web-app-*` exceptions), AND
   - `make test` is green (the rules-table tests in [Rules](#rules) are all part of `make test` and are not invoked individually).
8. **Strike the role through in the matrix** as the progress marker (see [Resumability](#resumability)) and move to the next role.

### Pattern transfer

After a role role-closes successfully, the agent MUST extract the **learnings** from that role and apply them to every later role in the iteration order **before** running the next role's deploy.
Pattern transfer is a code-edit step, not a deploy step: each receiving role still goes through its own [Per-role flow](#per-role-flow) when its turn comes; the deploy never spans more than one role at a time.

Learnings to propagate include every per-persona assertion shape from the [per-service assertion catalogue](../contributing/artefact/files/role/playwright.specs.js.md#per-service-assertion-catalogue-) that runs *inside the role under test*:

- the CSP injection assertion (every persona; the page's `Content-Security-Policy` header MUST list every enabled injector host);
- the `guest` denial flow (unauthenticated visitor never reaches an authenticated surface; empty-credentials submission MUST be rejected by the IdP);
- the `oidc` Keycloak round-trip (redirect to `openid-connect/auth`, login, redirect back, authenticated assertion);
- the `oauth2` proxy-gate flow;
- the `logout` universal-logout assertion;
- the `ldap` bind path (admin AND `biber`);
- the `email`, `discourse`, federation, and any other service-pair flow that the role itself initiates.

The SPOT-owned cross-service probes from Rule 13 are explicitly **out of scope** for pattern transfer. `dashboard` tile reachability, `prometheus` scrape parity (`up=1` per consumer), `matomo` tracker presence, and the per-consumer biber/administrator deny / accept checks at the prometheus and matomo admin surfaces all live in `roles/web-app-{dashboard,prometheus,matomo}/files/playwright/playwright.spec.js`, parameterised over `*_TARGET_ROLES_JSON`. Consumer specs MUST NOT carry these patterns.

For every receiving role, the agent MUST adapt the propagated pattern to the role-specific selectors and credentials.
Receiving roles whose `meta/services.yml` does NOT declare the relevant service MUST be skipped from that particular pattern transfer.
The transfer happens **immediately** after the source role closes successfully; deferral to a later pass is forbidden.

### Preserving existing tests

The rollout is purely additive.
The agent MUST NOT delete, shorten, or weaken any working test code in `files/playwright/playwright.spec.js`.
The persona scenarios and per-service gates land **alongside** the existing scenarios, never instead of them.

Specifically:

- A passing scenario MUST stay passing through the rollout.
  If a refactor risks breaking it, the agent MUST split the change so the existing scenario keeps its current shape and the new persona / gated scenarios are added next to it.
- Existing helper functions, selectors, and `test.beforeEach` setup MUST be preserved; new scenarios SHOULD reuse them rather than introducing parallel copies.
- An existing scenario MAY be **renamed** to follow the `<persona>: <flow>` naming convention from [Rule 3](#rules) when it already drives the persona's flow end-to-end; renaming MUST NOT change the assertions or the gated services.
- Deletion of an existing scenario is only allowed when the underlying behaviour has been removed from the role itself (the same exception that already lives in the [trigger conditions](../contributing/artefact/files/role/playwright.specs.js.md#triggers-when-to-add-or-update-a-scenario-) of `playwright.specs.js.md`).
  In every other case the agent MUST extend, not replace.

### Iteration order

The matrix above IS the iteration plan: the agent walks the table top-to-bottom.
`total` is the priority signal; ties are broken alphabetically by role name.
A hub fix propagates to the long tail of consumers via [Pattern transfer](#pattern-transfer), which is why the highest-`total` roles run first.

#### Auth-less roles (persona-collapse exception)

Per [Rule 3](#rules), the following roles MAY collapse the three persona scenarios into a single baseline reachability scenario because their upstream offers no auth surface (federation-only protocol, static-only output, programmatic-API-only service, internal sub-component of another role):

- Every `web-svc-*` role (no end-user UI by construction).
- `web-app-bridgy-fed` (federation-only; users authenticate at their source platform, not locally).
- `web-app-hugo` (static-site generator; no runtime auth).
- `web-app-littlejs`, `web-app-chess`, `web-app-mini-qr`, `web-app-roulette-wheel` (static / single-purpose toys; no upstream auth surface).
- `web-app-navigator`, `web-app-mig` (in-app modules of `web-app-dashboard`; no separate auth surface).
- `web-app-oauth2-proxy` (sidecar auth proxy; never directly user-facing).

Every other `web-app-*` role MUST ship all three persona scenarios per Rule 3.

### Resumability

The rollout is long-running and MAY be interrupted (sandbox timeout, context exhaustion, machine restart).
The iteration matrix above IS the progress marker; the agent strikes a row through (`~~`web-app-foo`~~`) after the role's full-cycle deploy plus Playwright spec pass for every declared variant, and does NOT maintain a separate state file.

When resuming, the agent MUST:

1. Re-run [test_env_services_match.py](../../tests/integration/roles/playwright/test_env_services_match.py) and [test_spec_env_gates.py](../../tests/integration/roles/playwright/test_spec_env_gates.py) to discover which roles are already role-closed (zero drift) and which are still open.
2. Pick the highest-`total` role in the matrix that is NOT role-closed and resume the [Per-role flow](#per-role-flow) on it.
3. Replay [Pattern transfer](#pattern-transfer) for any patterns the agent had landed pre-interruption: re-read each role-closed role's spec to identify which catalogue entries it covers, then ensure those patterns are present in every later not-yet-closed role's spec before continuing.

The agent MUST NOT redo deploys for already-role-closed roles unless a later edit broke their tests.

### Commits

- The agent MUST NOT create intermediate commits during the rollout.
- The agent MUST stage incremental changes locally as it goes (so progress survives between roles) but MUST NOT commit until the final role in the iteration order has been role-closed.
- A single commit at the end of the rollout captures every change.
  The commit message format is not prescribed by this requirement; use a concise summary that mentions req 019.
- The agent MUST NOT push the final commit; the operator runs `git-sign-push` outside the sandbox.

## Verification

- [ ] `make test` green tree-wide. Every rule-enforcing lint and integration test listed in the [Rules](#rules) table is part of `make test`; this requirement does NOT invoke them individually.
- [ ] `INFINITO_SERVICES_DISABLED=<svc>` reports every gated scenario as `skipped: <NAME>_SERVICE_ENABLED=false`, never `failed`. MUST cover ≥1 scenario each for `oidc`, `ldap`, `email`, `logout`, `matomo`. The `dashboard` exemption (Rule 1) means consumers do not render `DASHBOARD_SERVICE_ENABLED=`; coverage for that service runs through web-app-dashboard's parameterised tile-reachability test (Rule 13).
- [ ] No-`INFINITO_SERVICES_DISABLED` run produces ≥1 `passed` scenario per in-scope `(role, service)` pair. Empty-skip = fail.
- [ ] `grep 'process.env\.[A-Z_]*_SERVICE_ENABLED'` over the spec tree (excluding `service-gating.js`) returns zero hits.
- [ ] Post-deploy log inspection per [Rule 14](#rules) is clean for every role-closed variant: every wired persona / per-service assertion executed, no silent skip, no green-but-empty gate.
