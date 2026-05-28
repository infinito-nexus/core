# 018 - Playwright LDAP authentication coverage

## User Story

As a contributor maintaining the per-role Playwright suite, I want
every role whose `meta/services.yml` declares `ldap.enabled` (literal
`true` or the dynamic `"{{ 'svc-db-openldap' in group_names }}"` form)
to ship a Playwright scenario that exercises the LDAP-bind login path
end-to-end, so that the LDAP variant of the role's authentication
stack is verified independently from its OIDC counterpart.

## Context

[006 - Service-gated Playwright tests](README.md#archive)
established the `skipUnlessServiceEnabled(<service>)` contract:
scenarios gate on `<SERVICE>_SERVICE_ENABLED` flags so a deploy with
`disable=<service>` reports `skipped` instead of `failed`.
[004 - Generic RBAC auto-provisioning](README.md#archive)
plus [017 - Biber RBAC coverage](017-playwright-biber-rbac-coverage.md)
extend that contract to RBAC-aware non-admin scenarios.

Today most role specs gate their authenticated scenarios on `oidc`
only, even when the role's `meta/services.yml` also declares
`ldap.enabled` and a dedicated LDAP auth plugin / driver is wired in.
Consequence: a deploy with `disable=oidc` (LDAP-only mode)
makes every authenticated scenario `skip`, leaving the LDAP path
untested. The matrix-deploy variant lists in `meta/variants.yml`
typically include an LDAP-only variant exactly to exercise that
branch (see e.g. [web-app-opencloud/meta/variants.yml](../../roles/web-app-opencloud/meta/variants.yml)
where variant 1 sets `ldap.enabled: true` with `oidc.enabled: false`),
but the corresponding spec scenario does not exist yet.

`web-app-opencloud` is the trigger role for this requirement: its
`services.yml` was migrated to the dynamic-flag form for
`ldap.enabled`, both variants pin the LDAP branch on, but
[files/playwright/playwright.spec.js](../../roles/web-app-opencloud/files/playwright/playwright.spec.js)
has only `test.skip(!oidcEnabled, …)` gates. Closing the gap
consistently across the role tree is what this requirement tracks.

## Acceptance Criteria

### Policy

- [ ] Any role whose `meta/services.yml` declares `ldap.enabled` (literal
  `true` or the dynamic `"{{ 'svc-db-openldap' in group_names }}"`
  form per
  [test_dynamic_flags.py](../../tests/integration/roles/meta/services/test_dynamic_flags.py))
  AND ships an authenticated Playwright spec MUST include at least one
  scenario that drives the role's **LDAP-bind login path** end-to-end.
  The test MUST NOT route through Keycloak: it MUST hit whatever
  in-app LDAP auth surface the role exposes (Joomla core LDAP plugin,
  Jenkins LDAP security realm, OpenCloud LDAP basic-auth driver,
  Mattermost AD/LDAP login, etc.).
- [ ] The LDAP scenario MUST be gated via
  `skipUnlessServiceEnabled('ldap')` so a deploy with
  `disable=ldap` reports the scenario as
  `skipped: LDAP_SERVICE_ENABLED=false`, never `failed`.
- [ ] A role that ships BOTH `oidc.enabled` and `ldap.enabled`
  scenarios MUST keep them as **separate** test bodies. Combining the
  two flags in a single scenario is forbidden. The matrix-deploy
  variants exist precisely to drive each branch in isolation, and
  bundling them defeats the variant matrix.
- [ ] The LDAP scenario MUST exercise BOTH the canonical admin user
  and the canonical non-admin RBAC user `biber` (per
  [017](017-playwright-biber-rbac-coverage.md)). A role that only
  asserts the admin path under LDAP MUST flag the biber follow-up
  in its README until it is added.
- [ ] LDAP-driven persona scenarios MUST live INSIDE the persona bodies named `biber: <flow>` and `administrator: <flow>` per [019 Rule 3](019-playwright-meta-services-parity.md#rules); the per-persona LDAP gate is added via a separate `skipUnlessServiceEnabled('ldap')` call inside the existing persona body, not as a parallel ungated test.
  The persona-naming lint [test_naming.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_naming.py) is the role-closure gate; an additional ungated `ldap login` test next to the personas is forbidden by [019 Rule 5](019-playwright-meta-services-parity.md#rules).

### Env contract

- [ ] If the spec needs to know whether LDAP is enabled at runtime,
  it MUST read the `LDAP_SERVICE_ENABLED` flag exclusively through
  the `service-gating.js` helper from
  [006](README.md#archive). Direct
  `process.env.LDAP_SERVICE_ENABLED` reads in the spec are forbidden.
- [ ] No role MAY ship a role-local `<ROLE>_LDAP_ENABLED` env key as
  a workaround for the helper. The
  [test_playwright_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py)
  lint MUST stay green: any custom flag that survives must be
  consumed by the spec, otherwise it is dead config.

### Per-role audit

The list below was produced by grepping each role's
`meta/services.yml` for an `ldap` block with `enabled` set to
something other than `false`. Each checkbox MUST be closed by reading
the spec end to end, deciding whether the role exposes a
test-drivable LDAP auth surface, and then either adding the LDAP
scenario OR documenting in the commit message why the role is exempt
(e.g. the LDAP integration is consumer-side only, with no Playwright-
reachable login UI).

#### In-scope: LDAP scenario MUST be added

- [ ] [web-app-opencloud](../../roles/web-app-opencloud/): trigger role for this requirement; variant 1 is LDAP-only by design but the spec gates everything on `oidcEnabled`.
- [ ] [web-app-joomla](../../roles/web-app-joomla/): Joomla's core LDAP authentication plugin is the LDAP-variant surface per [006 audit row](README.md#archive). Pairs with the missing biber scenario from [017](017-playwright-biber-rbac-coverage.md).
- [ ] [web-app-jenkins](../../roles/web-app-jenkins/): Jenkins LDAP security realm is a separate auth provider from the OIDC plugin.
- [ ] [web-app-bookwyrm](../../roles/web-app-bookwyrm/): declares both `oidc` and `ldap` gates.
- [ ] [web-app-mattermost](../../roles/web-app-mattermost/): AD/LDAP login surface independent of OIDC.
- [ ] [web-app-friendica](../../roles/web-app-friendica/): LDAP module surface.
- [ ] [web-app-bigbluebutton](../../roles/web-app-bigbluebutton/): confirm whether the LDAP path has a Playwright-drivable surface; document the outcome.
- [ ] [web-app-akaunting](../../roles/web-app-akaunting/): LDAP authentication plugin.
- [ ] [web-app-discourse](../../roles/web-app-discourse/): LDAP plugin.
- [ ] [web-app-minio](../../roles/web-app-minio/): MinIO LDAP IDP.
- [ ] [web-app-flowise](../../roles/web-app-flowise/): confirm scope.
- [ ] [web-app-espocrm](../../roles/web-app-espocrm/): built-in LDAP authentication.
- [ ] [web-app-shopware](../../roles/web-app-shopware/): confirm scope.
- [ ] [web-app-odoo](../../roles/web-app-odoo/): `auth_ldap` module.
- [ ] [web-app-mobilizon](../../roles/web-app-mobilizon/): confirm scope.
- [ ] [web-app-openwebui](../../roles/web-app-openwebui/): confirm scope.

#### Out of scope: no LDAP scenario

The following declare an LDAP block but legitimately do not expose a
test-drivable LDAP login surface (consumer-side only, infrastructural,
or already covered by their own service-level test). Closing each
item is a NOOP unless a stale env key shows up.

- [ ] [web-app-keycloak](../../roles/web-app-keycloak/): IS the OIDC provider; LDAP federation is tested via Keycloak's own user-storage spec, not via a per-role Playwright surface.
- [ ] [web-app-fusiondirectory](../../roles/web-app-fusiondirectory/): IS the LDAP admin UI; its admin login already covers the LDAP bind path by construction.
- [ ] [svc-db-openldap](../../roles/svc-db-openldap/): backend service with no end-user UI; covered by integration tests, not Playwright.

### Verification

- [ ] After every role-local change [test_playwright_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py) MUST stay green.
- [ ] A run with `disable=oidc` (LDAP-only mode) MUST
  produce at least one `passed` LDAP scenario per role marked above
  as in-scope, never an empty-skip pass.
- [ ] A run with `disable=ldap` MUST report every LDAP
  scenario as `skipped: LDAP_SERVICE_ENABLED=false`, never
  `failed`.
- [ ] A grep `process.env\.LDAP_SERVICE_ENABLED` over the spec tree
  (excluding `roles/test-e2e-playwright/files/service-gating.js`)
  MUST return zero hits, proving every spec routes its LDAP gate
  through the helper rather than reading the flag directly.

## See Also

- [006 - Service-gated Playwright tests](README.md#archive)
- [017 - Playwright biber RBAC coverage](017-playwright-biber-rbac-coverage.md)
- [004 - Generic RBAC role auto-provisioning](README.md#archive)
