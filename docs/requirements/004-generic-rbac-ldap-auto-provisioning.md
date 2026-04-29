# 004 - Generic RBAC role auto-provisioning via OpenLDAP

## User Story

As an infrastructure maintainer, I want the OpenLDAP role to automatically
provision the RBAC groups for every role that declares an `rbac:` block in its
`config/main.yml`, gated on whether the role is deployed on this host
(present in `group_names`), so that operators declare roles once in role
config and the LDAP directory, Keycloak groups, and downstream OIDC claims
stay in lockstep without a per-role manual provisioning step.

## Acceptance Criteria

### Scope and gating

- [x] Every role under `roles/` that declares `rbac.roles.<role_name>` in its
  `config/main.yml` contributes its roles to the LDAP provisioning pipeline,
  independent of role category (`web-app-*`, `web-svc-*`, `svc-*`, etc.).
  Roles without an `rbac.roles` block contribute nothing and MUST NOT cause a
  failure.
- [x] A role's RBAC groups are provisioned into LDAP **only** when the role's
  `application_id` is present in `group_names` on the current host. Roles
  that declare an `rbac:` block but are not deployed on this host MUST NOT
  trigger any `ldapadd`/`ldapmodify` operation.
- [x] The existing backwards-compatible behavior stays intact: every
  deployed role with an `rbac:` block always receives at minimum an
  `administrator` group (as
  [build_ldap_role_entries](../../roles/svc-db-openldap/filter_plugins/build_ldap_role_entries.py)
  already enforces today), even when the role does not list
  `administrator` explicitly under `rbac.roles`.

### Naming convention

- [x] LDAP group `cn` follows the flat pattern `<application_id>-<role_name>`
  (e.g. `web-app-wordpress-editor`, `web-app-wordpress-administrator`,
  `web-app-pretix-organizer`). The existing `<application_id>-administrator`
  groups MUST continue to match this pattern without change so that current
  inventory overrides and bind DNs keep working.
- [x] The full DN uses the existing `ou=roles` container under
  `LDAP.DN.OU.ROLES` unchanged from the current administrator-group layout.
  Concretely the full DN pattern is:

  ```
  cn=<application_id>-<role_name>,ou=roles,<LDAP_DN_BASE>
  ```

  For WordPress this resolves to, for example:

  ```
  cn=web-app-wordpress-editor,ou=roles,dc=infinito,dc=example
  cn=web-app-wordpress-administrator,ou=roles,dc=infinito,dc=example
  ```

  The already-provisioned `cn=<application_id>-administrator,ou=roles,…`
  groups MUST keep their exact current DNs so existing bind/search filters
  in consumer apps continue to match. New auto-provisioned roles share
  the same `ou=roles` container, with no new OU introduced.

### Keycloak synchronization

- [x] Each auto-provisioned LDAP group MUST appear as a Keycloak group in
  the configured realm, via the existing LDAP → Keycloak sync path. No
  additional manual Keycloak configuration MUST be required beyond what is
  already in [roles/web-app-keycloak](../../roles/web-app-keycloak).
- [x] The Keycloak group mapper in the realm MUST propagate group membership
  into the OIDC `groups` claim (or the existing project-standard claim name)
  for every client that federates through Keycloak.

### OIDC-driven WordPress role mapping

- [x] WordPress MUST resolve a user's WordPress role from the OIDC `groups`
  claim delivered by Keycloak. No alternative path (direct LDAP bind from
  WordPress, manual WP user-meta editing, explicit per-user CLI command)
  MUST be required after the OIDC login completes.
- [x] The mapping Keycloak-group → WordPress-role MUST be defined so that
  group `web-app-wordpress-<role>` maps to WordPress role `<role>` for
  every role WordPress supports out of the box
  (`subscriber`, `contributor`, `author`, `editor`, `administrator`).
  If the current OIDC plugin configuration does not deliver this mapping,
  it MUST be adjusted in the same work item so that the Playwright
  verification below passes against a freshly-deployed stack.
- [x] Users who are not a member of any
  `web-app-wordpress-<role>` group MUST NOT receive an elevated WordPress
  role silently; falling back to the weakest role (`subscriber`) or
  rejecting the login is acceptable as long as it is deterministic.

### Idempotency

- [x] Re-running the provisioning on an already-provisioned LDAP directory
  MUST be a no-op with respect to group existence and role membership: no
  duplicate group, no removed membership, no spurious "changed" task
  result. Existing manual membership edits made outside the provisioning
  pipeline MUST NOT be overwritten unless the role config explicitly lists
  a `members:` attribute that contradicts them (out of scope for this
  requirement if not already modeled).
- [x] The Playwright verification (below) MUST itself be idempotent: after
  the test completes, `biber` MUST be a member of the same Keycloak and
  WordPress groups the test encountered at start. If the test added `biber`
  to a group during a run, the same run MUST remove `biber` from that group
  again during teardown; if the test found `biber` already a member, it
  MUST leave that membership in place. Starting state does not need to be
  "biber has no WordPress role"; the test must tolerate any start state
  and preserve it across a full run.

### Verification - Playwright test for WordPress

- [x] The existing [web-app-wordpress Playwright
  spec](../../roles/web-app-wordpress/files/playwright.spec.js) is extended
  (not replaced) to cover RBAC-auto-provisioning end-to-end. The baseline
  playwright requirements from
  [playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md)
  MUST still hold: file layout, runner integration, "when to write" scope,
  logged-out final state, no `test.only`/`test.skip`, traces+screenshots
  on failure, CSP assertions, OIDC flow, DOM assertion on a value sourced
  from `applications['web-app-wordpress']`.
- [x] The extended spec MUST cover three exemplary WordPress RBAC roles
  along the privilege spectrum:
  1. `subscriber` (read-only)
  2. `editor` (mid-tier write)
  3. `administrator` (full)
  These three roles MUST be asserted by literal name in the spec so
  regressions in the mapping are loud.
- [x] The extended spec MUST, for each of the three roles, run this
  end-to-end sequence:
  1. Log the Keycloak super administrator into the Keycloak admin UI in
     the master realm (not via an OIDC round-trip) using
     `KEYCLOAK_PERMANENT_ADMIN_USERNAME` / `KEYCLOAK_PERMANENT_ADMIN_PASSWORD`
     from [roles/web-app-keycloak/vars/main.yml](../../roles/web-app-keycloak/vars/main.yml),
     consistent with the pattern fixed in requirement 003.
  2. Assert that the Keycloak group `web-app-wordpress-<role>` already
     exists (since it was auto-created by the provisioning pipeline; the
     test MUST NOT create it).
  3. Add `biber` to that existing Keycloak group via the admin UI.
  4. Log `biber` out of any WordPress session (if any) and log `biber`
     back in via the OIDC flow on WordPress so the fresh OIDC claim
     arrives.
  5. Log the WordPress administrator in (via the OIDC-backed login if
     WordPress supports it, otherwise via the WP fallback form, following
     the existing admin-login helper in this spec) and navigate to the
     Users → All Users list.
  6. Assert that `biber`'s WordPress role equals `<role>`.
  7. Teardown: remove `biber` from the Keycloak group again so the final
     state matches the start state, fulfilling the idempotency criterion
     above.
- [x] The spec MUST perform the three role sequences **serially** in the
  defined order (subscriber → editor → administrator), so that a
  regression in one role does not mask regressions in the others.
- [x] The three role sequences MUST each end with `biber` removed from the
  Keycloak group that the sequence added; the final WordPress state MUST
  be a logged-out browser context.

### Iteration mode

- [x] This work uses the Role Loop from
  [role.md](../agents/action/iteration/role.md) against
  `web-app-wordpress` with `SERVICES_DISABLED="matomo,email"` unless
  otherwise agreed, and uses the Playwright Spec Loop from
  [playwright.md](../agents/action/iteration/playwright.md) for inner
  iteration on the extended spec.
- [x] The agent MUST start with
  `make deploy-fresh-purged-apps APPS=web-app-wordpress FULL_CYCLE=true
  SERVICES_DISABLED=matomo,email` to establish a baseline. Subsequent
  role-code changes use `make deploy-reuse-kept-apps APPS=web-app-wordpress`.
  Subsequent spec-only changes use
  [scripts/tests/e2e/rerun-spec.sh](../../scripts/tests/e2e/rerun-spec.sh).
- [x] Final confirmation uses
  `make deploy-fresh-purged-apps APPS=web-app-wordpress FULL_CYCLE=true
  SERVICES_DISABLED=matomo,email` with the extended Playwright spec
  passing in the same run.
