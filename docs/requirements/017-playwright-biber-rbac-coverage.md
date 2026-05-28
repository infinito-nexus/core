# 017 - Playwright `biber` non-admin RBAC coverage

## User Story

As a contributor maintaining the per-role Playwright suite, I want every
role whose login flow is RBAC-gated (OIDC and/or LDAP) to also exercise
the canonical non-admin user `biber` end-to-end, so that the RBAC
plumbing from
[004 - Generic RBAC role auto-provisioning](README.md#archive)
is verified per role rather than only on the privileged-admin path.

## Context

The repo treats `biber` as the canonical non-admin RBAC fixture: the
user is provisioned by `roles/svc-db-openldap` and exposed to specs
via the `lookup('users', 'biber')` filter. ~19 role specs already
consume `BIBER_USERNAME` / `BIBER_PASSWORD` from
`roles/<role>/templates/playwright.env.j2` and drive at least one
non-admin scenario (typically: SSO login via Keycloak, land on the
expected post-login surface, optionally assert that admin-only UI is
absent).

A static-analysis pass (added in
[tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py))
surfaced multiple roles that **declared** the `BIBER_*` env keys but
never read them in the spec; the env file was prepared, the spec was
never written. The most prominent example is `web-app-joomla`: it
ships an OIDC variant (`plg_system_keycloak`) and an LDAP variant
(core LDAP auth plugin) per
[006 - Service-gated Playwright tests](README.md#archive),
but the Playwright spec only exercises the admin login. A non-admin
biber landing-page assertion is missing and would catch RBAC
group-mapping drift introduced by 004.

This requirement closes that gap consistently across the role tree
rather than role by role.

## Acceptance Criteria

### Policy

- [ ] Any role whose `roles/<role>/files/playwright/playwright.spec.js` exercises
  an authenticated path AND whose `meta/services.yml` declares
  `oidc.enabled` OR `ldap.enabled` (literally or via the dynamic
  `"{{ '<role>' in group_names }}"` form per
  [test_dynamic_flags.py](../../tests/integration/roles/meta/services/test_dynamic_flags.py))
  MUST include at least one `biber`-driven scenario.
- [ ] The biber scenario MUST follow the `biber: <flow>` naming convention from [019 Rule 3](019-playwright-meta-services-parity.md#rules), enforced by [test_naming.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_naming.py).
  A role that legitimately cannot run a biber journey opts out via `PERSONA_BIBER_BLOCKED=true` in `templates/playwright.env.j2` per [019 Rule 11](019-playwright-meta-services-parity.md#rules).
- [ ] The biber scenario MUST gate on the same service flags that the
  matching admin scenario uses (typically `oidc`, `ldap`, or both),
  via the `skipUnlessServiceEnabled` helper from
  [006](README.md#archive). Operators running with
  `disable=oidc` MUST see the biber scenario as `skipped`
  with the canonical reason string, never as `failed`.
- [ ] The biber scenario MUST end on a deterministic post-login
  surface (a URL, a heading, or a stable role-specific selector) that
  is observable to a non-admin user. Asserting on admin-only UI from
  the biber session is forbidden. The point of the scenario is to
  prove the non-admin path works, not to re-test admin.
- [ ] Where the role's RBAC contract maps biber to a specific
  application role (e.g. `editor`, `member`), the assertion SHOULD
  pin that role: either by checking a role-scoped UI element or by
  asserting the absence of an admin-scoped element. A bare
  "post-login page rendered" check is acceptable as a starting point
  but MUST be flagged in the role README so a follow-up can tighten
  it.

### Env contract

- [ ] Every role that satisfies the policy above MUST declare
  `BIBER_USERNAME` and `BIBER_PASSWORD` (via
  `lookup('users', 'biber')`) in its
  `roles/<role>/templates/playwright.env.j2`. The
  [test_playwright_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py)
  lint MUST stay green: any declared `BIBER_*` key MUST be consumed
  by the role's spec or by a shared helper under
  `roles/test-e2e-playwright/files/`.
- [ ] Roles that legitimately do not exercise an authenticated UI
  (static content, pure backend services, identity providers tested
  separately) MUST NOT declare `BIBER_*` env keys. The env file is
  the registry; declaring without consuming is the failure mode this
  requirement fixes.

### Per-role audit

The list below was produced by grepping each
`roles/<role>/files/playwright/playwright.spec.js` for `biber|BIBER`. A role
appears under "missing" iff it has a Playwright spec, no biber
references, AND its policy classification (next column) says one is
expected. Each checkbox MUST be closed by reading the spec end to
end, deciding whether the role is in scope, and then either adding
the biber scenario (and the env keys) OR documenting in the
commit message why the role is exempt and removing it from this list.

#### In-scope: biber scenario MUST be added

- [ ] [web-app-joomla](../../roles/web-app-joomla/): OIDC
  (`plg_system_keycloak`) AND LDAP variants per
  [006](README.md#archive). Smoking gun for this
  requirement: env keys were declared, never consumed.
- [ ] [web-app-baserow](../../roles/web-app-baserow/): confirm OIDC/LDAP scope.
- [ ] [web-app-bookwyrm](../../roles/web-app-bookwyrm/): has both `oidc` and `ldap` gated paths in the spec; biber should ride one of them.
- [ ] [web-app-bluesky](../../roles/web-app-bluesky/): variant-A+ login-broker. Biber MAY require the broker's app-password handoff; document the outcome of the audit.
- [ ] [web-app-flowise](../../roles/web-app-flowise/): OIDC via oauth2-proxy.
- [ ] [web-app-jenkins](../../roles/web-app-jenkins/): OIDC plus LDAP variant.
- [ ] [web-app-akaunting](../../roles/web-app-akaunting/): OIDC plus LDAP variant.
- [ ] [web-app-minio](../../roles/web-app-minio/): OIDC plus LDAP variant.
- [ ] [web-app-taiga](../../roles/web-app-taiga/): OIDC.
- [ ] [web-app-gitea](../../roles/web-app-gitea/): OIDC plus optional LDAP.
- [ ] [web-app-postmarks](../../roles/web-app-postmarks/): confirm scope.

#### Identity providers: separate scope

- [ ] [web-app-keycloak](../../roles/web-app-keycloak/): IS the OIDC
  provider; biber's existence in Keycloak is the prerequisite for
  every other role's biber scenario. The role's spec already covers
  the realm-side flow; this requirement does NOT touch it. Audit the
  spec only to confirm no drift from
  [004](README.md#archive).
- [ ] [web-app-fusiondirectory](../../roles/web-app-fusiondirectory/):
  LDAP admin UI; biber as a *managed* user appears in the directory
  view, but the role's own login is admin-only. Audit and document.

#### Out of scope: no biber scenario

The following roles MUST NOT carry `BIBER_*` env keys nor a biber
scenario; closing each item is a NOOP except when a stale env-key
shows up; in that case remove it.

- [ ] [web-svc-cdn](../../roles/web-svc-cdn/), [web-svc-simpleicons](../../roles/web-svc-simpleicons/), [web-svc-xmpp](../../roles/web-svc-xmpp/), [web-svc-libretranslate](../../roles/web-svc-libretranslate/): backend services with no end-user UI.
- [ ] [web-app-hugo](../../roles/web-app-hugo/), [web-app-sphinx](../../roles/web-app-sphinx/), [web-app-bridgy-fed](../../roles/web-app-bridgy-fed/), [web-app-mig](../../roles/web-app-mig/): static or pure-publishing content with no authenticated path.
- [ ] [web-app-dashboard](../../roles/web-app-dashboard/), [web-app-matomo](../../roles/web-app-matomo/): own admin authentication is in scope of their own admin tests; biber-as-non-admin is not a meaningful surface here. Document and exempt.

### Verification

- [ ] After every role-local change [test_playwright_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py) MUST be green.
- [ ] A run with `disable=oidc,ldap` MUST report every biber
  scenario as `skipped: <FLAG>=false` per
  [006](README.md#archive), never as `failed`.
- [ ] A grep `process.env\.BIBER_(USERNAME|PASSWORD)` over the role
  tree MUST return at least one hit for every in-scope role above
  once the audit closes its checkbox.
