# 006 - Service-gated Playwright tests

## Update — MODE_CI retired

The `MODE_CI` flag introduced by this requirement was later retired in
favour of a direct `RUNTIME` check. The Playwright include in
[tasks/stages/02_server.yml](../../tasks/stages/02_server.yml) now
gates on `RUNTIME in ['dev', 'act', 'github']` (see
[cli/meta/runtime/__init__.py](../../cli/meta/runtime/__init__.py) for
how `RUNTIME` is detected and where it is baked into the inventory).
With that change the helper file `scripts/meta/env/ci.sh` and the
`INFINITO_MAKE_DEPLOY` / `INFINITO_SKIP_E2E` env-var plumbing were
removed: `make deploy-*` already bakes `RUNTIME=dev` into the
inventory at init time, CI runners detect `RUNTIME=act|github` from
their canonical env markers, and bare `ansible-playbook` from a
production shell stays at the default `RUNTIME=host` (no E2E). The
remainder of this document describes the historical MODE_CI design
for reference.

## User Story

As a contributor who runs `make deploy-*` with a subset of shared
services disabled (for example `SERVICES_DISABLED=matomo,email`), I want
Playwright specs to **skip** the individual tests that depend on a
disabled service instead of **failing** them, so that a deliberately
reduced deployment stays green and only real regressions surface in the
test output.

## Context

Infinito.Nexus apps routinely declare shared-service integrations in
their role config (`compose.services.<shared>.enabled`), and a deploy
can turn individual shared services off with `SERVICES_DISABLED=<list>`
without breaking the rest of the stack. The per-role Playwright specs
under `roles/<role>/files/playwright.spec.js` mix three classes of
tests:

1. **Baseline tests** that exercise the app's own behaviour (front-page
   reachability, CSP enforcement, canonical domain, static content).
   These MUST always run, because they are the minimum viable
   regression guard for the role.
2. **Shared-service integration tests** that assert the wiring between
   the app and another Infinito.Nexus service (OIDC round-trip,
   Matomo tracking snippet, outgoing email, Mastodon federation round-
   trip, Nextcloud search index, etc.).
3. **Composite tests** that combine several shared services in a single
   flow (for example the RBAC cycle from
   [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md),
   which assumes OIDC plus LDAP plus the RBAC client scope).

Today, class (2) and class (3) tests fail hard when a dependency is
disabled because they have no mechanism to learn what is present. This
requirement adds that mechanism, consistently, for every role's spec,
and retroactively migrates the existing specs onto it.

## Acceptance Criteria

### Source of truth: per-service boolean env flags

- [x] The test-e2e-playwright role MUST render one boolean env
  variable per gateable shared service into the role's staged
  Playwright `.env`, named `<SERVICE>_SERVICE_ENABLED` in
  UPPER_SNAKE_CASE (for example `OIDC_SERVICE_ENABLED=true`,
  `EMAIL_SERVICE_ENABLED=false`, `MATOMO_SERVICE_ENABLED=false`).
  Values MUST be the literal strings `"true"` or `"false"`. No other
  string (e.g. `1`, `0`, `yes`, empty) is permitted.
- [x] The rendered value MUST be derived deterministically from
  `applications[<role>].compose.services.<name>.enabled` minus every
  identifier in `SERVICES_DISABLED`. Two runs with the same role
  config and the same `SERVICES_DISABLED` MUST produce the same set
  of flag values.
- [x] The env template of the role under test
  (`roles/<role>/templates/playwright.env.j2`) IS the registry of
  gateable services for that role. A service MUST appear as a
  `<SERVICE>_SERVICE_ENABLED=...` line in that template for the spec
  to be allowed to gate on it. Adding a new gate therefore requires
  updating the env template AND the spec together.
- [x] Structurally always-present core services (the webserver-core,
  container runtime, DNS stack) MUST NOT be rendered as gate flags.
  The registry is reserved for shared-service integrations whose
  presence is meaningfully optional (OIDC, LDAP, email, matomo, CDN,
  prometheus, matrix, mastodon, talk, nextcloud search, onlyoffice,
  collabora, libretranslate, dashboard, simpleicons, and similar).

### Gate API in the Playwright specs

- [x] A small shared helper MUST be added at
  `roles/test-e2e-playwright/files/service-gating.js` and staged
  alongside every role spec by the same mechanism that stages the
  spec itself, so every `roles/<role>/files/playwright.spec.js`
  MUST import it as `require("./service-gating")` without any
  per-role setup. The helper MUST live at exactly that path; a spec
  MUST NOT inline the logic nor import a role-local copy. Its
  surface is:

  ```js
  isServiceEnabled("oidc")          // boolean
  requireService("oidc", testFn)    // test.skip() when disabled
  isServiceDisabledReason("email")  // e.g. "EMAIL_SERVICE_ENABLED=false"
  ```

- [x] The helper MUST hard-fail with `Unknown service: <name>` when
  called with an identifier that is not declared in the spec's env
  registry (i.e. no `<SERVICE>_SERVICE_ENABLED` line exists for it).
  A typo in `isServiceEnabled("oicd")` MUST surface as a test error,
  not as a silent disable.
- [x] The helper MUST use Playwright's native `test.skip()` mechanism
  (conditional skip with a reason string) rather than
  `test.describe.skip()` or runtime `return` statements, so skipped
  tests show up in the reporter as `- skipped: <reason>`.
- [x] The skip reason MUST name the disabling flag verbatim: for
  example `skipped: EMAIL_SERVICE_ENABLED=false`. This is the single
  diagnostic every contributor will consult when a test is missing
  from a run, so it MUST point at the exact env variable.
- [x] Specs MUST NOT read `<SERVICE>_SERVICE_ENABLED` variables
  directly via `process.env`. All reads go through the helper so the
  "unknown service hard-fails" guarantee is not bypassed.

### Backwards-compatible defaults

- [x] When a `<SERVICE>_SERVICE_ENABLED` variable is absent from the
  env (for example during local iteration via
  [rerun-spec.sh](../../scripts/tests/e2e/rerun-spec.sh) against an
  older staged `.env` that predates this requirement), the helper
  MUST treat that service as **enabled**. This preserves the current
  behaviour for iterative spec development against a fully-featured
  deploy.
- [x] An explicit `<SERVICE>_SERVICE_ENABLED=false` MUST be the only
  way to trigger a skip. There is no global "disable everything"
  toggle; operators who want only baseline tests set each relevant
  flag to `false` in their staged env, or deploy with
  `SERVICES_DISABLED=<list>` so Ansible renders them `false`
  automatically.

### Refactoring the existing specs

This requirement MUST NOT land as "new specs use the new helper;
old specs keep failing on disabled deps". Every spec that exists
today MUST be refactored in the same requirement iteration so the
tree becomes consistent.

Each of the checkboxes below MUST be closed individually by reading
the role's spec, pruning gates that the scenarios do not actually
exercise, adding gates that the audit discovers, and updating both
the spec and the role's `templates/playwright.env.j2` in lockstep.
The listed gates are the **best-effort pre-audit baseline** derived
from a grep scan; they are a starting point for each audit, not an
authoritative final list. The audit MUST be driven by reading each
scenario end to end. Baseline scenarios MUST stay ungated in every
case.

- [x] [web-app-bigbluebutton](../../roles/web-app-bigbluebutton/): audit spec; baseline gates: `oidc`, `ldap`, `dashboard`.
- [x] [web-app-dashboard](../../roles/web-app-dashboard/): audit spec; baseline gates: `oidc`, `matomo`, `simpleicons`. MUST NOT self-gate on `dashboard` because the role IS the dashboard.
- [x] [web-app-decidim](../../roles/web-app-decidim/): audit spec; baseline gates: `oidc`, `email`.
- [x] [web-app-discourse](../../roles/web-app-discourse/): audit spec; baseline gates: `oidc`, `dashboard`.
- [x] [web-app-fider](../../roles/web-app-fider/): audit spec; baseline gates: `oidc`, `email`, `dashboard`.
- [x] [web-app-friendica](../../roles/web-app-friendica/): audit spec; baseline gates: `oidc`, `ldap`, `dashboard`.
- [x] [web-app-gitea](../../roles/web-app-gitea/): audit spec; baseline gates: `oidc`, `email`.
- [x] [web-app-joomla](../../roles/web-app-joomla/): audit spec; baseline gates: `oidc`, `dashboard`.
- [x] [web-app-keycloak](../../roles/web-app-keycloak/): audit spec; baseline gates: `ldap` for federation scenarios. MUST NOT self-gate on `oidc` because Keycloak IS the OIDC provider; if the spec runs at all, OIDC is available by definition.
- [x] [web-app-mailu](../../roles/web-app-mailu/): audit spec; baseline gates: `oidc`, `dashboard`. MUST NOT self-gate on `email` because Mailu IS the email provider.
- [x] [web-app-matomo](../../roles/web-app-matomo/): audit spec; baseline gates: `dashboard`. MUST NOT self-gate on `matomo` because Matomo IS the matomo provider.
- [x] [web-app-matrix](../../roles/web-app-matrix/): audit spec; baseline gates: `oidc`, `email`, `matomo`, `dashboard`.
- [x] [web-app-mattermost](../../roles/web-app-mattermost/): audit spec; baseline gates: `oidc`, `email`, `dashboard`.
- [x] [web-app-nextcloud](../../roles/web-app-nextcloud/): audit spec; baseline gates: `oidc`, `ldap`, `email`, `dashboard`, `onlyoffice`, `collabora`, `talk`. Each integration scenario MUST gate on its own flag; a single omnibus gate across the set MUST NOT be used.
- [x] [web-app-odoo](../../roles/web-app-odoo/): audit spec; baseline gates: `oidc`, `email`, `dashboard`.
- [x] [web-app-openwebui](../../roles/web-app-openwebui/): audit spec; baseline gates: `oidc`, `dashboard`.
- [x] [web-app-peertube](../../roles/web-app-peertube/): audit spec; baseline gates: `oidc`, `dashboard`.
- [x] [web-app-pixelfed](../../roles/web-app-pixelfed/): audit spec; baseline gates: `oidc`, `email`, `dashboard`.
- [x] [web-app-prometheus](../../roles/web-app-prometheus/): audit spec; baseline gates: `oidc`, `email`, `dashboard`.
- [x] [web-app-taiga](../../roles/web-app-taiga/): audit spec; baseline gates: `oidc`, `dashboard`.
- [x] [web-app-wordpress](../../roles/web-app-wordpress/): audit spec; baseline gates: `oidc`, `ldap` (from [004](004-generic-rbac-ldap-auto-provisioning.md)); `discourse` (from [007](007-wordpress-discourse-post-round-trip.md)).
- [x] [web-app-yourls](../../roles/web-app-yourls/): audit spec; baseline gates: `oidc`, `email`, `dashboard`.
- [x] [web-svc-cdn](../../roles/web-svc-cdn/): audit spec before adding any gate; CDN is a static-origin service and its spec is likely all-baseline. The audit outcome MUST be documented in the commit that closes this checkbox.
- [x] [web-svc-simpleicons](../../roles/web-svc-simpleicons/): audit spec; baseline gate: `oidc` if the admin-facing scenario uses it; otherwise close this item with "all-baseline" and no gate added.
- [x] After the refactor the following post-conditions MUST all hold:
  - Baseline scenarios of every spec keep passing when `SERVICES_DISABLED`
    is empty.
  - With `SERVICES_DISABLED=matomo,email,discourse` and a role under test
    that touches all three, the related scenarios appear as `skipped`
    in the Playwright reporter with skip reasons naming the exact env
    flags, and the overall run is green.
  - A grep for `process.env.[A-Z_]*_SERVICE_ENABLED` in the spec tree
    MUST return zero hits outside the helper implementation, proving
    no spec reads the flags directly.

### CI / deploy detection for the playwright gate

The include of the Playwright runner in
[tasks/stages/02_server.yml](../../tasks/stages/02_server.yml) is
currently gated on `DOCKER_IN_CONTAINER | bool`. That condition is
structurally wrong: it reflects "is Ansible running inside a Docker
container" (defined in
[group_vars/all/00_general.yml](../../group_vars/all/00_general.yml)
as a fact probe of `ansible_facts['env']['container']`) and is a
reasonable proxy for "am I in CI" only by accident. A bare-metal host
that happens to run the playbook inside a container stays stuck with
E2E tests enabled; a CI job whose container probe does not surface
the env marker silently skips them. This requirement replaces the
accidental proxy with an explicit intent variable.

- [x] A new top-level variable `MODE_CI` MUST be defined in
  [group_vars/all/01_modes.yml](../../group_vars/all/01_modes.yml)
  alongside the existing `MODE_DUMMY`, `MODE_DEBUG`, `MODE_ASSERT`
  etc. family, as a boolean fact. Its value MUST be `true` when ANY of the
  following holds, and `false` otherwise:
  - The env var `GITHUB_ACTIONS` is set to a truthy value (the GitHub
    Actions runner's canonical marker).
  - The env var `ACT` is set to a truthy value (nektos/act's
    canonical marker for local GitHub Actions emulation).
  - The env var `INFINITO_MAKE_DEPLOY` is set to a truthy value. Each
    deploy entry-point script under
    [scripts/tests/deploy/local/deploy/](../../scripts/tests/deploy/local/deploy/)
    sources `scripts/meta/env/ci.sh` (since deleted)
    at startup, which exports the marker. This makes `make`-driven
    local deploys (which call those entry-point scripts) count as
    the "intentionally CI-like" case without the Makefile having to
    inline the export.
- [x] `MODE_CI` MUST be strictly orthogonal to
  `DOCKER_IN_CONTAINER`. The existing `DOCKER_IN_CONTAINER` variable
  MUST keep its current container-detection semantics and its current
  consumers (MariaDB port exposure, hostname task, WireGuard gating,
  etc.) MUST NOT be migrated to `MODE_CI`. The two flags answer
  two different questions and MUST continue to do so.
- [x] The include of `test-e2e-playwright` in
  [tasks/stages/02_server.yml](../../tasks/stages/02_server.yml)
  MUST switch its `when:` from `DOCKER_IN_CONTAINER | bool` to
  `MODE_CI | bool`. Any other callsite in the tree that gates
  test execution specifically (rather than containerization) MUST be
  audited in the same requirement iteration and migrated if the
  semantic intent was CI.
- [x] The export needed to flip `MODE_CI` to `true` MUST live in a
  single SPOT under
  `scripts/meta/env/ci.sh` (since deleted):

  ```bash
  : "${INFINITO_MAKE_DEPLOY:=1}"
  export INFINITO_MAKE_DEPLOY
  ```

  Every deploy entry-point script under
  [scripts/tests/deploy/local/deploy/](../../scripts/tests/deploy/local/deploy/)
  MUST source `scripts/meta/env/ci.sh` at startup, e.g.:

  ```bash
  # shellcheck source=scripts/meta/env/ci.sh
  source "scripts/meta/env/ci.sh"
  ```

  No Makefile recipe MAY hard-code the literal
  `INFINITO_MAKE_DEPLOY=1`, and `scripts/meta/env/all.sh` MUST NOT
  source `ci.sh` (the marker MUST surface only when a deploy actually
  runs, never for unrelated `make test*` / `make build*` recipes that
  share the same `BASH_ENV`). When `MODE_CI` later gains additional
  contributing markers, or when the marker name changes, exactly one
  line in `ci.sh` has to move.
- [x] The set of scripts that MUST source `ci.sh` is every deploy
  entry-point under
  [scripts/tests/deploy/local/deploy/](../../scripts/tests/deploy/local/deploy/),
  without exception: today that is `fresh-kept-all.sh`,
  `fresh-kept-app.sh`, `fresh-purged-app.sh`, `reuse-kept-all.sh`,
  and `reuse-kept-app.sh`. Every future deploy entry-point MUST
  source it the same way. Raw `ansible-playbook` invocations from a
  developer shell MUST NOT set the flag, so the default is "E2E tests stay
  out of the way unless explicitly requested".
- [x] A `make deploy-*` target MAY additionally allow an explicit
  opt-out via `INFINITO_SKIP_E2E=1`. When set, `MODE_CI` MUST
  evaluate to `false` regardless of the other markers. This gives a
  contributor a fast iteration loop that deploys without paying the
  Playwright cost.
- [x] The new flag and its truthiness sources MUST be documented in
  [documentation.md](../contributing/documentation.md)'s environment
  conventions (or the closest existing SPOT if a more appropriate
  page exists) so a contributor does not have to grep the Makefile to
  understand when the Playwright stage runs.

### Verification

- [x] A unit-level test on the test-e2e-playwright role MUST assert
  the env-rendering logic: given a synthetic
  `applications[<role>].compose.services` fact and a synthetic
  `SERVICES_DISABLED` list, the rendered set of
  `<SERVICE>_SERVICE_ENABLED` lines MUST match an explicit expected
  set. At least three fixtures MUST be covered: nothing disabled,
  one service disabled, all service-gated flags disabled.
- [x] A unit-level test on the helper MUST cover all observable
  behaviours: the `true` path, the `false` path, the absent-variable
  (default-enabled) path, and the hard-fail path for an unknown
  service name.
- [x] At least one role spec MUST include an integration-level test
  that drives the helper both ways in the same run: one scenario
  gated on a service known to be enabled (MUST execute) and one
  scenario gated on a service forced off via a locally-scoped env
  override (MUST report `skipped` with the expected reason).
- [x] A CI smoke run with `SERVICES_DISABLED=matomo,email` MUST be
  added (or extended from the existing deploy cycle) that deploys at
  least one matomo-using and one email-using role and asserts that
  the related Playwright tests report as `skipped`, not as `failed`.
- [x] An end-to-end smoke MUST cover the `MODE_CI` gate matrix:
  - A GitHub Actions run MUST produce `MODE_CI=true` and
    therefore include the `test-e2e-playwright` stage.
  - A [nektos/act](https://nektos.com/) local run MUST produce the
    same truthy result via the `ACT` marker and include the stage.
  - **Every** `make deploy-*` target on a developer workstation MUST
    produce `MODE_CI=true` via `INFINITO_MAKE_DEPLOY=1` and
    include the stage. This applies to the full family without
    exception: `deploy-fresh-purged-apps`, `deploy-reuse-kept-apps`,
    any `FULL_CYCLE=true` wrapper, and any future
    `deploy-<variant>` target added later. The verification MUST
    therefore not assert this for one named target; it MUST grep
    [Makefile](../../Makefile) for the full set of `deploy-*`
    targets and assert the export is present in each recipe (for
    example via a small static test on the Makefile).
  - A raw `ansible-playbook` invocation with none of the markers
    set MUST produce `MODE_CI=false` and skip the stage cleanly.
  - Any of the `make deploy-*` invocations with `INFINITO_SKIP_E2E=1`
    MUST evaluate to `MODE_CI=false` and skip the stage.

### Documentation

- [x] The Playwright contributor guide
  [playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md)
  already carries the normative rules for service gating under the
  Option B shape. It MUST stay in sync with this requirement. Any
  clarification added to this requirement that tightens the contract
  MUST be mirrored there, and vice versa.
- [x] The Playwright framework SPOT
  [Playwright Tests](../contributing/actions/testing/playwright.md)
  MUST gain a short section that documents the
  `<SERVICE>_SERVICE_ENABLED` contract, the helper API, and the
  backwards-compatible default. The page MUST follow
  [documentation.md](../contributing/documentation.md) (RFC 2119,
  link-text style, emojis after headings, no em dashes).
- [x] Each role README that documents its Playwright spec MUST state
  which shared services its gated scenarios depend on, so an operator
  planning a reduced deploy can predict which scenarios will skip.
