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

- [x] Any role whose `roles/<role>/files/playwright/playwright.spec.js` exercises an authenticated path AND whose `meta/services.yml` declares `sso.enabled` OR `ldap.enabled` (literally or via the dynamic `"{{ '<role>' in group_names }}"` form per [test_dynamic_flags.py](../../tests/integration/roles/meta/services/test_dynamic_flags.py)) MUST include at least one `biber:` scenario, or opt out via `PERSONA_BIBER_BLOCKED` per the next criterion. [test_naming.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_naming.py) enforces this for every `web-app-*` role.
- [x] The biber scenario MUST follow the `biber: <flow>` naming convention from 019 Rule 3, enforced by [test_naming.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_naming.py).
  A role that legitimately cannot run a biber journey opts out via `PERSONA_BIBER_BLOCKED=true` in `templates/playwright.env.j2` per 019 Rule 11.
- [ ] A biber scenario that does not run the shared `runBiberFlow` persona MUST gate on the same service flags that the matching admin scenario uses (typically `sso`, `ldap`, or both), via the `skipUnlessServiceEnabled` helper from [006](README.md#archive). Operators running with `disable=sso` MUST see such a scenario as `skipped` with the canonical reason string, never as `failed`. The shared `runBiberFlow` persona itself skips only through `PERSONA_BIBER_BLOCKED` or the auth-less collapse, as [test_strict_mode.py](../../tests/lint/ansible/roles/web-app/playwright/persona/test_strict_mode.py) enforces.
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

- [x] Every role in scope of the policy above whose biber scenario is not opted out via `PERSONA_BIBER_BLOCKED=true` MUST declare `BIBER_USERNAME` and `BIBER_PASSWORD` (via `lookup('users', 'biber')`) in its `roles/<role>/templates/playwright.env.j2`. The [test_playwright_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py) lint MUST stay green: any declared `BIBER_*` key MUST be consumed by the role's spec or by a shared helper under `roles/test-e2e-playwright/files/`.
- [x] Roles that legitimately do not exercise an authenticated UI
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

- [x] [web-app-joomla](../../roles/web-app-joomla/): OIDC
  (`plg_system_keycloak`) AND LDAP variants per
  [006](README.md#archive). Smoking gun for this
  requirement: env keys were declared, never consumed.
- [x] [web-app-baserow](../../roles/web-app-baserow/): confirm OIDC/LDAP scope.
- [x] [web-app-bookwyrm](../../roles/web-app-bookwyrm/): the role declares no `ldap` service, so biber rides the `sso`-gated paths ([test-rbac.js](../../roles/web-app-bookwyrm/files/playwright/test-rbac.js), [test-profile-sync.js](../../roles/web-app-bookwyrm/files/playwright/test-profile-sync.js)).
- [x] [web-app-bluesky](../../roles/web-app-bluesky/): variant-A+ login-broker. Biber MAY require the broker's app-password handoff; document the outcome of the audit.
- [x] [web-app-flowise](../../roles/web-app-flowise/): OIDC via oauth2-proxy. [test-biber-persona.js](../../roles/web-app-flowise/files/playwright/test-biber-persona.js) carries two `sso`-gated `biber:` scenarios (oauth2 gate refusal, `mcp` role group sign-in) reading `BIBER_USERNAME` / `BIBER_PASSWORD`; `PERSONA_BIBER_BLOCKED` is gone from `templates/playwright.env.j2`.
- [x] [web-app-jenkins](../../roles/web-app-jenkins/): OIDC plus LDAP variant.
- [x] [web-app-minio](../../roles/web-app-minio/): OIDC plus LDAP variant.
- [x] [web-app-taiga](../../roles/web-app-taiga/): OIDC.
- [x] [web-app-gitea](../../roles/web-app-gitea/): OIDC plus optional LDAP.
- [x] [web-app-postmarks](../../roles/web-app-postmarks/): [test-biber-persona.js](../../roles/web-app-postmarks/files/playwright/test-biber-persona.js) carries an `sso`-gated `biber:` scenario asserting the oauth2 gate refuses biber outside the postmarks administrator group; `PERSONA_BIBER_BLOCKED` is gone from `templates/playwright.env.j2`.
- [x] [web-svc-xmpp](../../roles/web-svc-xmpp/): moved from the out-of-scope list. The spec reads `BIBER_*` and carries `ldap`-gated biber scenarios (web admin and API refuse biber, biber's vCard comes from LDAP); the shared persona journey stays blocked because the web admin admits only administrators.
- [x] [web-app-dashboard](../../roles/web-app-dashboard/): moved from the out-of-scope list. [test-biber-persona.js](../../roles/web-app-dashboard/files/playwright/test-biber-persona.js) runs the shared biber persona, blocked only while `sso` is disabled.
- [x] [web-app-matomo](../../roles/web-app-matomo/): moved from the out-of-scope list. [auth.spec.js](../../roles/web-app-matomo/files/playwright/auth.spec.js) carries an `sso`-gated `biber:` scenario asserting the Keycloak login of an account without a Matomo role yields no Matomo session or account; the shared persona journey stays blocked.
- [web-app-akaunting](../../roles/web-app-akaunting/): no longer in scope. The role is end of life (`lifecycle: eol` in its `meta/services.yml`, see its [README](../../roles/web-app-akaunting/README.md)): since Akaunting 3.1 every create needs an `api.akaunting.com` account key, so no biber journey can be driven unattended.

#### Identity providers: separate scope

- [x] [web-app-keycloak](../../roles/web-app-keycloak/): IS the OIDC
  provider; biber's existence in Keycloak is the prerequisite for
  every other role's biber scenario. The role's spec already covers
  the realm-side flow; this requirement does NOT touch it. Audit the
  spec only to confirm no drift from
  [004](README.md#archive).
- [x] [web-app-fusiondirectory](../../roles/web-app-fusiondirectory/):
  LDAP admin UI; biber as a *managed* user appears in the directory
  view, but the role's own login is admin-only. Audit and document.

#### Out of scope: biber persona stub only

The persona contract in [playwright.specs.js.md](../../docs/contributing/artefact/files/role/playwright.specs.js.md) requires a `biber:` scenario in every spec, so the following roles MAY carry a biber persona stub that skips (opted out via `PERSONA_BIBER_BLOCKED=true`, or collapsed because the role renders no `APP_BASE_URL` / `CANONICAL_DOMAIN`), but MUST NOT declare `BIBER_USERNAME` / `BIBER_PASSWORD` that no scenario consumes. Closing each item is a NOOP except when a stale env key shows up; in that case remove it. [web-svc-xmpp](../../roles/web-svc-xmpp/), [web-app-dashboard](../../roles/web-app-dashboard/) and [web-app-matomo](../../roles/web-app-matomo/) moved to the in-scope list because they now carry consumed `BIBER_*` keys and biber scenarios.

- [x] [web-svc-cdn](../../roles/web-svc-cdn/), [web-svc-simpleicons](../../roles/web-svc-simpleicons/), [web-svc-libretranslate](../../roles/web-svc-libretranslate/): services with no end-user UI session. None declares `BIBER_USERNAME` / `BIBER_PASSWORD`; cdn and simpleicons collapse their biber stub, libretranslate opts out via `PERSONA_BIBER_BLOCKED=true`.
- [x] [web-app-hugo](../../roles/web-app-hugo/), [web-app-docs](../../roles/web-app-docs/), [web-app-bridgy-fed](../../roles/web-app-bridgy-fed/), [web-app-meta](../../roles/web-app-meta/): static or pure-publishing content with no authenticated path. None declares `BIBER_USERNAME` / `BIBER_PASSWORD`; each opts its biber stub out via `PERSONA_BIBER_BLOCKED=true`.

### Verification

- [x] After every role-local change [test_playwright_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py) MUST be green. `make test-lint` (`Makefile`) runs it on every change, and it is green on the tree that closes this audit.
- [ ] A run with `disable=sso,ldap` MUST report every biber scenario that does not run the shared `runBiberFlow` persona as `skipped: <FLAG>=false` per [006](README.md#archive), never as `failed`.
- [x] A grep `process.env\.BIBER_(USERNAME|PASSWORD)` over the role tree MUST return at least one hit for every in-scope role above once the audit closes its checkbox. A role whose only biber scenario runs the shared `runBiberFlow` persona (web-app-dashboard) counts through the helper's `readEnv("BIBER_USERNAME")` / `readEnv("BIBER_PASSWORD")` in [biber.js](../../roles/test-e2e-playwright/files/personas/biber.js).
