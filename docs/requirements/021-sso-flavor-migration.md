# 021 - SSO Flavor Migration (oauth2 + oidc → unified `sso` service)

## User Story

As a contributor, I want a single canonical SSO service block in every role's
`meta/services.yml` so that the integration shape is uniform regardless of
which protocol flavor (OIDC, OAuth2-proxy, SAML) a role's upstream consumes.
The two parallel `services.oauth2.*` and `services.oidc.*` blocks merge into
one `services.sso.*` block discriminated by a `flavor:` field. The dedicated
`web-app-oauth2-proxy` role disappears; its proxy-sidecar logic becomes a
first-class capability of `web-app-keycloak`, the canonical SSO provider.

## Background

Today every role that wires SSO ships up to TWO independent service blocks in
`meta/services.yml`:

| Block | Purpose | Truthy in |
|---|---|---|
| `services.oidc.{enabled,shared}` | Marks the role as an OIDC relying party. Drives the OIDC client registration in Keycloak and the in-app login redirect. | ~38 roles |
| `services.oauth2.{enabled,shared,origin.{host,port}}` | Marks the role as front-fronted by an `oauth2-proxy` sidecar that performs the auth dance and forwards `X-Forwarded-User`/`X-Forwarded-Email` headers to the upstream. | ~10 roles |

The two blocks are mutually exclusive on the runtime path (a single role's
auth surface is either OIDC-direct or oauth2-proxy-gated, never both), and a
test ([test_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py))
already forbids both `enabled` keys being literal `True` at the same time.
Despite that, three roles ship both blocks in different truthy shapes:

| Role | `oidc.enabled` | `oauth2.enabled` | `oauth2.origin` | Resolution |
|---|---|---|---|---|
| `web-app-bookwyrm` | truthy (group-gated) | truthy (group-gated) | yes | `flavor: oauth2` — bookwyrm runs behind oauth2-proxy header auth; the `oidc:` block is vestigial from a prior integration attempt. |
| `web-app-gitea` | truthy (group-gated) | (unset) | yes | `flavor: oidc` — gitea's own auth uses OIDC against Keycloak; the `oauth2.origin` block is dead and MUST be dropped. |
| `web-app-friendica` | truthy (group-gated) | (unset) | yes | `flavor: oidc` — friendica's own auth uses OIDC; the `oauth2.origin` block is dead and MUST be dropped. |

The duplication has real cost:

- Two independent lint suites enforce overlapping contracts
  ([test_oauth2_contract.py](../../tests/lint/ansible/roles/meta/test_oauth2_contract.py),
  [test_sso.py](../../tests/lint/ansible/roles/web-app/integration/test_sso.py),
  [test_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py),
  [test_acl_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_acl_mutual_exclusive.py),
  [test_dynamic_flags.py](../../tests/integration/roles/meta/services/test_dynamic_flags.py)).
- Consumer code (lookup plugins, filter plugins, templates) branches on both
  `services.oauth2.enabled` and `services.oidc.enabled`.
- The standalone `web-app-oauth2-proxy` role is a "helper role" whose only
  purpose is to render an oauth2-proxy config file into a sidecar consumer's
  volume directory. It carries its own `meta/main.yml`, `meta/services.yml`,
  `meta/server.yml`, `meta/variants.yml`, plus 5 templates and a `tasks/main.yml`
  guard against direct invocation. The role has no application surface of its
  own and exists only as a per-consumer template injector — a shape that
  contradicts the rest of the role taxonomy.
- The `web-app-keycloak` role already IS the SSO provider, but does not own
  the per-consumer proxy-sidecar wiring. The current split forces every
  oauth2-proxy-gated role to depend on TWO providers (`web-app-keycloak` for
  the IdP, `web-app-oauth2-proxy` for the sidecar config) even though both
  are facets of the same SSO concern.

This requirement collapses the two blocks into one and dissolves the
`web-app-oauth2-proxy` role into `web-app-keycloak` as a per-consumer
capability — mirroring the `prometheus` pattern where `web-app-prometheus`
owns both the central server and the per-consumer scrape wiring.

## Confirmed Decisions

These ten decisions were confirmed by the operator before the requirement was
written and are NOT subject to re-litigation during implementation.

| # | Decision | Rationale |
|---|---|---|
| 1 | The unified block is `services.sso.{enabled,shared,flavor,...}` with `flavor:` as a discriminator string. | Single block per role; protocol detail is a field, not a top-level key. |
| 2 | `flavor:` enum: `oidc`, `oauth2`, `saml`. Default is `oidc` when omitted. | OIDC is the dominant flavor (~38 of ~48 SSO-consuming roles); SAML is a placeholder for future per-flavor defaults. |
| 3 | Per-flavor sub-keys live under `services.sso.<flavor>.<…>` (e.g. `services.sso.oauth2.origin.{host,port}`); shared keys live at `services.sso.{enabled,shared,flavor}`. | Keeps flavor-specific shape isolated and self-describing. |
| 4 | Migration rule: if either old block had `enabled` truthy, the new `services.sso.enabled` is truthy with the same Jinja form (typically `"{{ 'web-app-keycloak' in group_names }}"`); same rule for `shared`. | Preserves runtime behaviour exactly for single-block roles; the 3 dual-block roles use the explicit per-role mapping in the [Background](#background) table. |
| 5 | Big-bang migration in a single atomic PR. No backward-compat shim, no path aliasing, no transitional period that reads both old and new shapes. | The two blocks would have to be kept consistent during any transition window; cheaper to migrate everything at once. |
| 6 | The new naming is `sso` (NOT `oidc`-with-flavors). The old `services.oauth2.*` and `services.oidc.*` paths cease to exist. | `sso` is protocol-neutral; keeping the name `oidc` would mislead readers about what the block now covers. |
| 7 | `oauth2` (as a top-level service key) is removed entirely from the repository. Every reference migrates to the new `sso` shape. | Avoids leaving a half-deprecated key that future contributors mistake for live. |
| 8 | The `roles/web-app-oauth2-proxy/` directory is deleted. Its proxy-sidecar templating moves into `roles/web-app-keycloak/` and is invoked per-consumer during a consumer role's deploy. | Eliminates the "helper role with no application surface" anti-pattern; centralises the SSO concern in one provider role. |
| 9 | `web-app-keycloak/meta/services.yml` declares `provides: [sso]` (analog to the `prometheus` provider pattern, see [019 Rule 13](019-playwright-meta-services-parity.md#rules)). | Single source of truth for who provides SSO; consumers' `services.sso.enabled` toggles need to round-trip against this provider declaration. |
| 10 | The two existing mutual-exclusion tests ([test_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py), [test_acl_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_acl_mutual_exclusive.py)) are deleted, not adapted. The new contract is "one block per role, period" — there is nothing to be mutually exclusive about. | Mutual exclusion was an artefact of having two blocks; removing the duplication removes the test's reason to exist. |

## Target Schema

### Unified `services.sso` block

`meta/services.yml` excerpt for a role that consumes SSO:

```yaml
# Pure-OIDC role (the common case, ~38 roles).
sso:
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
  # flavor omitted → default 'oidc'

# OAuth2-proxy-gated role (~10 roles).
sso:
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
  flavor:  oauth2
  oauth2:
    origin:
      host: application
      port: "{{ lookup('config', application_id, 'services.<entity>.ports.internal.http') }}"

# Nextcloud's plugin-flavor sub-discriminator (currently services.oidc.flavor).
sso:
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
  flavor:  oidc        # explicit only because we override the per-plugin sub-flavor
  oidc:
    plugin: oidc_login # or 'sociallogin' — resolved by lookup('sso_oidc_plugin')
```

### Provider declaration in `web-app-keycloak`

`roles/web-app-keycloak/meta/services.yml` excerpt:

```yaml
keycloak:
  image: …
  provides: [sso]      # new — analog to web-app-prometheus' `provides: [prometheus]`
  # …existing service body…
```

### Path rewrites

| Old path | New path |
|---|---|
| `services.oidc.enabled` | `services.sso.enabled` |
| `services.oidc.shared` | `services.sso.shared` |
| `services.oidc.flavor` | `services.sso.oidc.plugin` (Nextcloud only — renamed for clarity; the old key collided with the new top-level `flavor` discriminator) |
| `services.oauth2.enabled` | `services.sso.enabled` (with `services.sso.flavor: oauth2`) |
| `services.oauth2.shared` | `services.sso.shared` (with `services.sso.flavor: oauth2`) |
| `services.oauth2.origin.host` | `services.sso.oauth2.origin.host` |
| `services.oauth2.origin.port` | `services.sso.oauth2.origin.port` |
| `services.<entity>.ports.local.oauth2` | `services.<entity>.ports.local.sso` |
| `OAUTH2_PROXY_*` (env / Jinja vars) | `SSO_PROXY_*` |

The legacy `oauth2-proxy` Docker image and `oauth2-proxy-keycloak.cfg`
filename stay as-is (they are upstream artifact names), but every project-internal
identifier moves to the `sso_*` namespace.

## Touchpoint Inventory

Six layers, ~67 files total. The exact file count is approximate — the
migration must sweep the tree and absorb every match `grep`-style.

### Layer 1: role configuration (~48 files)

- Every `roles/<role>/meta/services.yml` that contains an `oauth2:` or `oidc:`
  top-level key. The grep set as of this writing:
  `bookwyrm, friendica, gitea, nextcloud, postmarks, baserow, bluesky, prometheus`
  (plus ~10 oauth2-proxy-gated roles and ~30 oidc-only roles — full sweep
  during implementation, not enumerated here).
- Every `roles/<role>/meta/variants.yml` that pins `services.oauth2.{…}` or
  `services.oidc.{…}` in a variant override. Confirmed touched:
  `postmarks, baserow, bookwyrm, fusiondirectory, oauth2-proxy` (the
  last one disappears wholesale with its role).
- Every `roles/<role>/vars/main.yml` that derives a Python-side or
  Jinja-side variable from `services.oauth2.*` / `services.oidc.*`.
  Confirmed touched: `bookwyrm, bluesky, oauth2-proxy, keycloak`.

### Layer 2: lookup / filter plugins (~10 files)

| Plugin | Current reference | After |
|---|---|---|
| [plugins/lookup/oidc_flavor.py](../../plugins/lookup/oidc_flavor.py) | Reads `services.oidc.flavor` + `services.ldap.enabled` for Nextcloud. | Renamed to `plugins/lookup/sso_oidc_plugin.py`; reads `services.sso.oidc.plugin` + `services.ldap.enabled`. |
| [plugins/lookup/database.py](../../plugins/lookup/database.py) | (no change expected) | — |
| [plugins/filter/compose_volumes.py](../../plugins/filter/compose_volumes.py) | Branches on `services.oauth2.enabled`. | Branches on `services.sso.flavor == 'oauth2'`. |
| [roles/web-app-keycloak/filter_plugins/redirect_uris.py](../../roles/web-app-keycloak/filter_plugins/redirect_uris.py) | Reads `services.oauth2.*` per consumer to build redirect URI list. | Reads `services.sso.*` per consumer; flavor-aware. |
| Any new lookup needed to enumerate `flavor == 'oauth2'` consumers for the sidecar templating step. | (new) | `plugins/lookup/sso_proxy_consumers.py` — returns the list of roles whose merged config has `services.sso.flavor == 'oauth2'` AND `services.sso.enabled` truthy, used by web-app-keycloak to render per-consumer sidecar configs. |

### Layer 3: templates (~15 files)

- `roles/sys-svc-proxy/templates/vhost/basic.conf.j2` — branches on
  oauth2 vs oidc; rewrite to read `services.sso.flavor`.
- `roles/sys-svc-proxy/templates/location/html.conf.j2` — same.
- `roles/sys-svc-compose/templates/base.yml.j2` — same.
- `roles/web-app-keycloak/templates/nginx/helper_iframes.conf.j2` — reads
  oauth2 host/port; rewrite to `services.sso.oauth2.origin.{host,port}`.
- `roles/web-app-keycloak/templates/nginx/sso.html.conf.j2` (if it branches
  on flavor — confirm during sweep).
- Every `roles/<role>/templates/playwright.env.j2` that renders
  `OAUTH2_*_SERVICE_ENABLED` or `OIDC_*_SERVICE_ENABLED` flags. The grep set
  is wide (~25 templates).
- Every `roles/<role>/templates/env.j2` / `compose.yml.j2` that injects
  oauth2-proxy environment variables.
- `roles/web-app-oauth2-proxy/templates/oauth2-proxy-keycloak.cfg.j2`,
  `container.yml.j2`, `endpoint.conf.j2`, `following_directives.conf.j2`,
  `style.css.j2` — MOVE under `roles/web-app-keycloak/templates/sso_proxy/`
  (file names kept; the `oauth2-proxy-keycloak.cfg` upstream-config name
  stays per the [Target Schema](#target-schema) note).

### Layer 4: tests (~12 files)

- DELETE: [tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py),
  [tests/integration/iam/oauth2_oidc/test_acl_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_acl_mutual_exclusive.py)
  (per [Decision #10](#confirmed-decisions)).
- RENAME and rewrite:
  [tests/lint/ansible/roles/meta/test_oauth2_contract.py](../../tests/lint/ansible/roles/meta/test_oauth2_contract.py)
  → `test_sso_contract.py`. The new contract: when
  `services.sso.flavor == 'oauth2'` AND `services.sso.enabled` is potentially
  truthy, the role MUST carry `services.sso.oauth2.origin.{host,port}` AND
  `services.<entity>.ports.local.sso`.
- UPDATE: [tests/lint/ansible/roles/web-app/integration/test_sso.py](../../tests/lint/ansible/roles/web-app/integration/test_sso.py)
  — rewrite all references to point at `services.sso.*`.
- UPDATE: [tests/integration/roles/meta/services/test_dynamic_flags.py](../../tests/integration/roles/meta/services/test_dynamic_flags.py)
  — replace `oauth2`/`oidc` flag names with `sso`.
- UPDATE: [tests/integration/roles/meta/services/run_after/test_services_explicit.py](../../tests/integration/roles/meta/services/run_after/test_services_explicit.py)
  — same.
- ADD: a new lint test that fails if any role's `meta/services.yml` contains a
  top-level `oauth2:` or `oidc:` key, or if any source file outside this
  requirement document references `services.oauth2.*` / `services.oidc.*` /
  `web-app-oauth2-proxy`. Modelled on the legacy-paths guard added in
  [008](008-role-meta-layout.md#tests).
- ADD: a unit test for the renamed `sso_oidc_plugin` lookup that mirrors
  [tests/unit/plugins/lookup/test_oidc_flavor.py](../../tests/unit/plugins/lookup/test_oidc_flavor.py).
- UPDATE: every Playwright spec that reads `OAUTH2_SERVICE_ENABLED` (e.g.
  `roles/web-app-prometheus/files/playwright/playwright.spec.js`) to read
  `SSO_SERVICE_ENABLED` instead. The `service-gating.js` helper, the
  `*_TARGET_ROLES_JSON` manifests, and the persona helpers carry across
  unchanged.

### Layer 5: suppression / nocheck markers

- Every `# nocheck: playwright-service-flag: <…oauth2…>` / `<…oidc…>`
  comment in a role's `meta/services.yml` migrates to the new flag name.
- The rule-key catalogue at [docs/contributing/actions/testing/suppression.md](../contributing/actions/testing/suppression.md)
  must reflect any new lint rule keys introduced (e.g. `sso-contract`
  replacing `oauth2-contract`).

### Layer 6: docs (~8 files)

- UPDATE [docs/requirements/006-playwright-service-gated-tests.md](README.md#archive)
  — replace OAUTH2 / OIDC examples with SSO.
- UPDATE [docs/requirements/019-playwright-meta-services-parity.md](019-playwright-meta-services-parity.md)
  — the matrix rows mention `oauth2` / `oidc` in their `notes` columns;
  rewrite to `sso (flavor: oauth2)` / `sso (flavor: oidc)`.
- UPDATE [docs/requirements/008-role-meta-layout.md](008-role-meta-layout.md)
  — the file currently mentions `oidc_flavor` lookup; renamed in the
  consumer-path table.
- UPDATE [docs/contributing/artefact/files/role/playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md)
  — the per-service catalogue table merges the `oidc` and `oauth2` rows into
  one `sso` row with a flavor sub-column.
- UPDATE these role READMEs that reference oauth2-proxy or oidc directly:
  - `roles/web-app-keycloak/README.md` — document the new SSO ownership
    (sidecar templating + provider declaration).
  - `roles/web-app-kix/README.md` (current `services.oauth2` reference).
  - `roles/web-app-bookwyrm/README.md`, `roles/web-app-gitea/README.md`,
    `roles/web-app-friendica/README.md` (the three dual-block roles —
    document the per-role flavor resolution).
- DELETE `roles/web-app-oauth2-proxy/README.md`, `Setup.md`, `TODO.md` along
  with the role directory itself.

## Migration Sequence

The migration MUST land in a single atomic PR (per [Decision #5](#confirmed-decisions)).
Within that PR, the agent MUST execute the steps in this order so the working
tree is never in a half-migrated state between steps:

1. **Provider declaration first.** Add `provides: [sso]` to
   `roles/web-app-keycloak/meta/services.yml`. Move the oauth2-proxy templates
   from `roles/web-app-oauth2-proxy/templates/` into
   `roles/web-app-keycloak/templates/sso_proxy/`. Port the oauth2-proxy
   templating task (currently `roles/web-app-oauth2-proxy/tasks/main.yml`)
   into a new `roles/web-app-keycloak/tasks/sso_proxy.yml` that iterates
   per-consumer via a `sso_proxy_consumers` lookup. Update web-app-keycloak's
   own `meta/services.yml` to merge in the proxy-sidecar dependencies that
   used to live in `web-app-oauth2-proxy/meta/services.yml`.
2. **New lookup plugin.** Add `plugins/lookup/sso_proxy_consumers.py` (new)
   and rename `plugins/lookup/oidc_flavor.py` → `plugins/lookup/sso_oidc_plugin.py`
   with the path-rewrite in [Target Schema](#target-schema). Update the
   companion unit test under `tests/unit/plugins/lookup/`.
3. **Role-side schema rewrite.** Sweep every `roles/<role>/meta/services.yml`,
   `roles/<role>/meta/variants.yml`, and `roles/<role>/vars/main.yml`.
   Collapse `oidc:` and `oauth2:` blocks into a single `sso:` block per the
   migration rule in [Decision #4](#confirmed-decisions); for the 3
   dual-block roles, apply the per-role flavor in the [Background](#background)
   table.
4. **Consumer-path rewrites.** Sweep every Python plugin, Jinja template,
   `tasks/*.yml`, and `env.j2`. Rewrite `services.oauth2.*` /
   `services.oidc.*` paths per [Target Schema](#target-schema).
   `services.<entity>.ports.local.oauth2` → `services.<entity>.ports.local.sso`.
   `OAUTH2_PROXY_*` env names → `SSO_PROXY_*`.
5. **Test rewrites.** Delete the two mutual-exclusion tests; rename the
   oauth2 contract lint; update the dynamic-flags + run-after tests; add
   the new "no legacy oauth2/oidc keys" guard lint.
6. **Doc + README sweep.** Apply the [Layer 6](#layer-6-docs-8-files) edits.
7. **Role deletion.** Delete `roles/web-app-oauth2-proxy/` in its entirety
   (the templates have already moved in step 1, the consumer-side wiring
   has been redirected in step 4, and the per-role provider responsibility
   now lives in web-app-keycloak).

The agent MUST run `make test` after step 7 and fix every fallout before
committing. `make test` is the sole correctness gate; no per-test
cherry-picking.

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A consumer template silently relies on the **literal key name** `oauth2` (e.g. a Jinja `{{ 'oauth2' in services }}` check) and breaks invisibly when the key is renamed to `sso`. | Medium | High (silent auth bypass) | The new "no legacy oauth2/oidc keys" guard lint (step 5) flag-greps the source tree; any remaining literal `'oauth2'` / `'oidc'` string outside known-allow paths fails the lint. |
| The 3 dual-block roles' per-role flavor decision turns out wrong at runtime (e.g. friendica was actually relying on the dead `oauth2.origin` block I declared dead). | Low | High (auth chain breaks for that role) | Full-cycle deploy each of the 3 roles standalone before the PR ships — the validation set in [Validation Apps](#validation-apps) covers all three. Playwright biber+administrator personas (per [019 Rule 3](019-playwright-meta-services-parity.md#rules)) catch a broken auth chain end-to-end. |
| Deleting `web-app-oauth2-proxy/` breaks a downstream consumer that hard-codes the role name in an `include_role:` / `import_role:` directive somewhere. | Low | Medium (role-not-found at deploy time) | The role's own `tasks/main.yml` currently `fail`s on direct invocation, so no role should be calling it directly. Grep-verify before deletion: `grep -rn 'web-app-oauth2-proxy' roles/ cli/ utils/ plugins/` MUST return only hits inside the role itself (which is about to be deleted) and inside the docs that the [Layer 6](#layer-6-docs-8-files) sweep will update. |
| The new `services.sso.flavor` default (`oidc`) is silently picked up by a role that today has neither `oauth2:` nor `oidc:` blocks but does have an `sso:` block written by a future contributor who expected the field to be required. | Low | Low (defensive default) | The new contract lint (step 5) MUST require `services.sso.flavor` to be explicit whenever `services.sso.enabled` is potentially truthy AND the role is not the SSO provider itself. |

## Acceptance Criteria

### Schema

- [ ] Every role's `meta/services.yml` that previously had `oidc:` or
      `oauth2:` (or both) carries a single unified `sso:` block per
      [Target Schema](#target-schema).
- [ ] The `sso.flavor` field is an explicit string in
      `{oidc, oauth2, saml}` whenever `sso.enabled` is potentially truthy.
- [ ] The 3 dual-block roles (bookwyrm, friendica, gitea) carry the per-role
      flavor recorded in the [Background](#background) table.
- [ ] `roles/web-app-keycloak/meta/services.yml` declares
      `provides: [sso]` on the `keycloak` service entry.
- [ ] No `meta/services.yml` in the repository contains a top-level
      `oauth2:` or `oidc:` key.

### Consumer paths

- [ ] Every Python plugin, Jinja template, `tasks/*.yml`, `env.j2`,
      `vars/main.yml`, and `playwright.env.j2` reference to
      `services.oauth2.*` is rewritten to `services.sso.*` per
      [Target Schema](#target-schema).
- [ ] Every reference to `services.oidc.*` is rewritten to `services.sso.*`
      (with the explicit exception that `services.oidc.flavor` for Nextcloud
      becomes `services.sso.oidc.plugin`).
- [ ] Every `services.<entity>.ports.local.oauth2` reference is rewritten
      to `services.<entity>.ports.local.sso`.
- [ ] Every project-internal `OAUTH2_PROXY_*` identifier (env var, Jinja
      variable, lookup key) is rewritten to `SSO_PROXY_*`. The upstream
      `oauth2-proxy` Docker image name and the `oauth2-proxy-keycloak.cfg`
      upstream-config filename stay as-is.

### Provider role

- [ ] `roles/web-app-oauth2-proxy/` is deleted in its entirety.
- [ ] The 5 templates from `roles/web-app-oauth2-proxy/templates/` live
      under `roles/web-app-keycloak/templates/sso_proxy/`.
- [ ] `roles/web-app-keycloak/tasks/sso_proxy.yml` renders the per-consumer
      sidecar config via the new `sso_proxy_consumers` lookup.
- [ ] No `include_role`/`import_role` directive references `web-app-oauth2-proxy`.

### Tests

- [ ] [tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py)
      and [tests/integration/iam/oauth2_oidc/test_acl_mutual_exclusive.py](../../tests/integration/iam/oauth2_oidc/test_acl_mutual_exclusive.py)
      are deleted; the parent `tests/integration/iam/oauth2_oidc/` directory
      is removed if it becomes empty.
- [ ] [tests/lint/ansible/roles/meta/test_oauth2_contract.py](../../tests/lint/ansible/roles/meta/test_oauth2_contract.py)
      is renamed to `test_sso_contract.py` and rewritten to check the
      `services.sso.flavor == 'oauth2'` shape.
- [ ] [tests/lint/ansible/roles/web-app/integration/test_sso.py](../../tests/lint/ansible/roles/web-app/integration/test_sso.py)
      and [tests/integration/roles/meta/services/test_dynamic_flags.py](../../tests/integration/roles/meta/services/test_dynamic_flags.py)
      and [tests/integration/roles/meta/services/run_after/test_services_explicit.py](../../tests/integration/roles/meta/services/run_after/test_services_explicit.py)
      reference the new `sso` flag exclusively.
- [ ] A new lint test under `tests/lint/` MUST fail if any source file (other
      than this requirement document and historical changelogs) contains the
      literal strings `services.oauth2.`, `services.oidc.`, `web-app-oauth2-proxy`,
      or top-level `oauth2:` / `oidc:` keys in a `meta/services.yml`.
- [ ] The `sso_oidc_plugin` lookup has a unit test that mirrors the existing
      [test_oidc_flavor.py](../../tests/unit/plugins/lookup/test_oidc_flavor.py).
- [ ] `make test` is green tree-wide.

### Documentation

- [ ] [006](README.md#archive),
      [008](008-role-meta-layout.md), and
      [019](019-playwright-meta-services-parity.md) examples and tables are
      updated to the new SSO naming.
- [ ] [docs/contributing/artefact/files/role/playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md)
      catalogue merges the oidc and oauth2 rows into one `sso` row with a
      flavor sub-column.
- [ ] [docs/contributing/actions/testing/suppression.md](../contributing/actions/testing/suppression.md)
      reflects any renamed lint rule keys.
- [ ] Role READMEs touched per [Layer 6](#layer-6-docs-8-files) are updated.

### Atomicity & validation

- [ ] The migration lands as a single atomic change set: schema edits,
      consumer-path rewrites, role deletion, test updates, doc updates all
      ship in one commit (or one tight commit sequence within one PR).
- [ ] After the refactor, a repository-wide `grep -rE '(services\.oauth2|services\.oidc|web-app-oauth2-proxy)'`
      returns zero matches outside (a) this requirement file and (b)
      historical changelogs.
- [ ] Every file and role touched by this refactoring is also simplified
      and refactored where possible, following the principles in
      [principles.md](../contributing/design/principles.md).

## Validation Apps

The following standalone deploys MUST succeed end-to-end (deploy + Playwright
biber + administrator personas per [019 Rule 3](019-playwright-meta-services-parity.md#rules))
after the refactor. The set covers every flavor + every dual-block role.

| App | Flavor | Why it's in the validation set |
|---|---|---|
| `web-app-keycloak` | n/a (provider) | The provider itself — `provides: [sso]` + per-consumer sidecar templating must work for any downstream to work. |
| `web-app-nextcloud` | `oidc` (with `services.sso.oidc.plugin` sub-flavor) | Exercises the renamed `sso_oidc_plugin` lookup and the sub-flavor field. |
| `web-app-bookwyrm` | `oauth2` | One of the 3 dual-block roles; validates the per-role mapping. |
| `web-app-gitea` | `oidc` | One of the 3 dual-block roles; validates the dead-oauth2-block removal. |
| `web-app-friendica` | `oidc` | One of the 3 dual-block roles; validates the dead-oauth2-block removal. |
| `web-app-prometheus` | `oauth2` | Canonical pure-oauth2-proxy-gated role; cross-checks the sidecar-templating path. |
| `web-app-dashboard` | `oidc` | Canonical pure-OIDC role with silent-SSO chain; cross-checks the default-flavor path. |

```bash
INFINITO_APPS="web-app-keycloak web-app-nextcloud web-app-bookwyrm web-app-gitea web-app-friendica web-app-prometheus web-app-dashboard" \
  make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

## Prerequisites

Before starting any implementation work, the agent MUST read
[AGENTS.md](../../AGENTS.md) and follow all instructions in it.

## Implementation Strategy

The agent MUST execute this requirement **autonomously**. Open clarifications
only when a decision is genuinely ambiguous and would otherwise block progress;
default to the intent already captured in this document and proceed. Avoid
back-and-forth questions on choices that are already specified above
(flavor enum, default flavor, dual-block role mappings, role deletion).

1. Read [Role Loop](../agents/action/iteration/role.md) before starting.
2. Execute the [Migration Sequence](#migration-sequence) steps 1–7 in order.
3. Run `make test` until green.
4. Run the validation deploys listed above.

## Commit Policy

- The agent MUST NOT create any git commit until **every** Acceptance Criterion
  in this document is checked off (`- [x]`).
- A single commit (or a tight, related sequence) lands the whole atomic refactor;
  no half-migrated intermediate commits.
- When all ACs are met, `make test` is green, and the validation apps deploy
  cleanly, the agent instructs the operator to run `git-sign-push` outside the
  sandbox (per [CLAUDE.md](../../CLAUDE.md)). The agent MUST NOT push.
