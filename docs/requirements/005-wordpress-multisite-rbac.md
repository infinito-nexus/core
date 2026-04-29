# 005 - WordPress Multisite support for OIDC-driven RBAC

## User Story

As an operator who runs WordPress Multisite behind Infinito.Nexus' shared
Keycloak realm, I want the OIDC-to-role mapping from
[004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
to support **per-site access control and per-site role assignment**, so
that a Keycloak group membership maps to a role on a specific WordPress
site in a Multisite network. Users without a matching group for a given
site MUST NOT have any access to that site. Network-wide administration
remains expressible as a separate, site-independent group.

To make this possible cleanly, this requirement ALSO migrates the LDAP
layout for every role that declares an `rbac:` block from the current
flat `cn=<application_id>-<role_name>,ou=roles,...` pattern to a uniform
per-application OU hierarchy, so that WordPress' per-tenant expansion is
a natural extension of the same tree rather than a special case sitting
next to a flat namespace.

## Context

[004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
provisions all RBAC groups flat under `ou=roles` with the naming
convention `<application_id>-<role_name>`. This scales for apps whose
user directory is a single flat namespace (Nextcloud, Gitea, Keycloak
itself, etc.), but it produces two problems that this requirement fixes
together:

1. **No tenancy axis.** WordPress Multisite needs per-site role scoping.
   A flat namespace cannot express "user biber is editor on site A
   only" without embedding the tenant identifier into the `cn` with a
   convention-based separator, which is fragile.
2. **No structural grouping by application.** Every app's groups live
   in the same flat OU, so auditing, ACL scoping, and future per-app
   tenancy extensions have to filter by `cn` prefix. That works, but
   it treats application identity as a string convention instead of a
   directory structure.

This requirement therefore unifies every role's LDAP layout around a
per-application namespacing scheme. The implementation keeps every
LDAP group entry as a direct child of `ou=roles,...` with a CN of
shape `<application_id>-<role_name>` (and, for tenant-aware apps,
`<application_id>-<tenant_id>-<role_name>`). The Keycloak group tree
is reconstructed on top of that flat LDAP layout by **per-application
`group-ldap-mapper`s** (one mapper per deployed app), each anchored at
`/roles/<application_id>` and using the LDAP entry's `description`
attribute as the visible Keycloak group name. The resulting Keycloak
tree (and therefore the OIDC `groups` claim with `full.path=true`)
mirrors the requested hierarchy exactly:

```
/roles/<application_id>/<role_name>
/roles/<application_id>/<tenant_id>/<role_name>
```

Empirically, Keycloak's shared `group-ldap-mapper` with
`preserve.group.inheritance=true` collapses every duplicate LDAP group
*name* into a single Keycloak group, so DN-based hierarchy with role
names that recur across applications (`administrator`, `editor`, ...)
is dropped at sync time. Splitting the mapper per application avoids
that collision: each per-app mapper sees only its own role groups
(`(cn=<application_id>-*)` filter) and its `description`-driven
naming yields clean leaf names without redundant prefixes.

## Acceptance Criteria

### Schema extension in role config

- [x] A new optional key `rbac.tenancy` MUST be supported in
  `roles/<role>/config/main.yml`. Its schema is:

  ```yaml
  rbac:
    tenancy:
      axis: "domain"                    # one of: "domain", "none" (default: "none")
      source: "server.domains.canonical"
    roles:
      <role_name>:
        description: "..."
        scope: "per_tenant"             # one of: "per_tenant" (default when axis != "none"), "global"
  ```

- [x] When `rbac.tenancy.axis == "none"` or the `rbac.tenancy` block is
  absent, the role MUST still be migrated to the per-application OU
  layout described under "LDAP provisioning" below. It MUST NOT fall
  back to the pre-005 flat naming, because a partial migration would
  leave the tree in an inconsistent state.
- [x] When `rbac.tenancy.axis == "domain"`, the pipeline MUST read the
  Jinja path declared in `rbac.tenancy.source` (default
  `server.domains.canonical`) from the role's `lookup('applications',
  application_id)`, resolve it to a list of tenant identifiers, and
  expand tenant-scoped roles per identifier. The `source` field MUST be
  validated at provisioning time; an unresolvable path MUST fail the
  provisioning task with a clear error, not silently skip the role.
- [x] Tenant identifiers MUST always be DNS domains drawn from
  `server.domains.canonical`. The pipeline MUST NOT accept arbitrary
  strings as tenant IDs. This keeps the identifier set bounded by the
  hostname character class (`[a-z0-9.-]`, lowercased), which is safe
  to embed verbatim as an LDAP `ou=<tenant_id>` without escape
  handling. The pipeline MUST lowercase the domain before embedding
  it, so case differences between Ansible config and rendered DN
  cannot drift.
- [x] Within a tenant-aware role, individual `rbac.roles.<role_name>`
  entries MAY set `scope: "global"` to declare a role that is NOT
  expanded per tenant. `network-administrator` on WordPress is the
  reference case. The default when the `scope` key is omitted MUST be
  `per_tenant`.

### LDAP provisioning

- [x] Every role that declares an `rbac:` block MUST be provisioned
  with a per-application namespace. The implementation keeps every
  LDAP group as a direct child of `ou=roles,...` and encodes the
  application (and tenant, if any) into the CN with hyphen separators.
  The DN patterns are:

  ```
  # role in a non-tenant app (tenancy.axis == "none" or absent)
  cn=<application_id>-<role_name>,ou=roles,<LDAP_DN_BASE>

  # role in a tenant-aware app, per tenant (scope: "per_tenant", default)
  cn=<application_id>-<tenant_id>-<role_name>,ou=roles,<LDAP_DN_BASE>

  # role in a tenant-aware app, not expanded per tenant (scope: "global")
  cn=<application_id>-<role_name>,ou=roles,<LDAP_DN_BASE>
  ```

  Concrete examples:

  ```
  # non-tenant app: Nextcloud
  cn=web-app-nextcloud-administrator,ou=roles,dc=infinito,dc=example

  # tenant-aware app: WordPress Multisite with canonical domains
  # ["blog.example", "shop.example"]
  cn=web-app-wordpress-blog.example-editor,ou=roles,dc=infinito,dc=example
  cn=web-app-wordpress-blog.example-subscriber,ou=roles,dc=infinito,dc=example
  cn=web-app-wordpress-shop.example-editor,ou=roles,dc=infinito,dc=example
  cn=web-app-wordpress-network-administrator,ou=roles,dc=infinito,dc=example
  ```

  Per-application "container" `groupOfNames` entries
  (`cn=<application_id>,ou=roles,...`) are also created so a tree-aware
  consumer can navigate the hierarchy via LDAP `member` references; the
  Keycloak mapping does not depend on them, since per-application
  Keycloak `group-ldap-mapper`s anchor each app's role groups at
  `/roles/<application_id>` independently.

- [x] The flat pattern from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  (`cn=<application_id>-<role_name>,ou=roles,...`) MUST NOT be emitted
  by [build_ldap_role_entries](../../roles/svc-db-openldap/filter_plugins/build_ldap_role_entries.py)
  anymore after this requirement is implemented.
- [x] The intermediate `groupOfNames` containers
  (`cn=<application_id>`, and for tenant-aware apps
  `cn=<tenant_id>,cn=<application_id>`) MUST be auto-created by the
  provisioning pipeline so that an operator does not need a separate
  step to prepare the RBAC tree.
- [x] The gate from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  still applies: provisioning for a role (flat or hierarchical) MUST
  happen only when the role's `application_id` is present in
  `group_names` on the current host. Roles not deployed on this host
  MUST NOT emit either their application OU or any of its children.
- [x] The implicit `administrator` group from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  MUST continue to be auto-added for every deployed role with an
  `rbac:` block. In the new layout it lands at
  `cn=administrator,cn=<application_id>,ou=roles,...` for non-tenant
  roles, and per tenant under
  `cn=administrator,cn=<tenant_id>,cn=<application_id>,ou=roles,...`
  for tenant-aware roles. The auto-add MUST NOT happen at the flat
  level anymore.

### RBAC group-path lookup plugin

Hard-coding the OIDC group path with `[RBAC.GROUP.NAME, '<app>-<role>'] | path_join`
was acceptable under
[004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
because the path had a single shape. With the hierarchical layout and
the tenant layer introduced here, every consumer that computes a group
path has to understand the same rules (per-app OU, tenant placement,
`scope: "global"` exceptions, `RBAC.GROUP.NAME` prefix). Centralising
this in a lookup plugin removes the class of bugs where one consumer
updates and another does not.

- [x] A new Ansible lookup plugin MUST be added at
  `plugins/lookup/rbac_group_path.py`. Its contract is:

  ```jinja
  # non-tenant app
  "{{ lookup('rbac_group_path', application_id='web-app-yourls',
             role='administrator') }}"
  # => "roles/web-app-yourls/administrator"

  # tenant-aware app, per-tenant role
  "{{ lookup('rbac_group_path', application_id='web-app-wordpress',
             role='editor', tenant='blog.example') }}"
  # => "roles/web-app-wordpress/blog.example/editor"

  # tenant-aware app, scope=global role
  "{{ lookup('rbac_group_path', application_id='web-app-wordpress',
             role='network-administrator') }}"
  # => "roles/web-app-wordpress/network-administrator"
  ```

- [x] The plugin MUST read `RBAC.GROUP.NAME` from the
  [group_vars](../../group_vars/all/00_general.yml) SPOT rather than
  hardcoding `"roles"`, so a platform-wide rename of the top-level
  group container stays a one-line change.
- [x] The plugin MUST consult the target application's `rbac` config
  (`lookup('applications', application_id).rbac`) and MUST:
  - Fail with a clear error when the requested `role` is not declared
    under `rbac.roles.<role>` or is not the implicit `administrator`
    added by
    [build_ldap_role_entries](../../roles/svc-db-openldap/filter_plugins/build_ldap_role_entries.py).
  - Fail with a clear error when a `tenant` argument is passed to a
    role whose resolved `scope` is `"global"`, or when a
    non-tenant-aware application receives a `tenant` argument.
  - Fail with a clear error when a tenant-aware per-tenant role is
    requested WITHOUT a `tenant` argument.
- [x] Every existing callsite that today uses the pattern
  `[RBAC.GROUP.NAME, '<literal>'] | path_join` or
  `[RBAC.GROUP.NAME, application_id ~ '-<role>'] | path_join` MUST be
  migrated to `lookup('rbac_group_path', ...)` in the same requirement
  iteration. A grep for `RBAC.GROUP.NAME` outside
  [group_vars](../../group_vars/), the plugin implementation, and
  documentation MUST return zero hits after this requirement is
  implemented.
- [x] A unit-level test in
  [tests/unit/plugins/lookup/](../../tests/unit/plugins/lookup/) MUST
  cover all three shapes (non-tenant, tenant-aware per-tenant,
  tenant-aware global) and all three failure modes (unknown role,
  tenant-on-global, missing-tenant-on-per-tenant).
- [x] [tests/integration/lookups/test_usage.py](../../tests/integration/lookups/test_usage.py),
  which already asserts that every defined lookup plugin is actually
  referenced in production code, MUST stay green after the plugin is
  added. The callsite migration above guarantees that `rbac_group_path`
  has real consumers on day one, so the plugin does not need a
  separate allowlist entry.

### Keycloak synchronization

- [x] The Keycloak LDAP group federation mapper MUST be reconfigured
  to preserve group inheritance so that Keycloak's group tree mirrors
  the LDAP OU tree. Every per-application OU in LDAP MUST appear as a
  Keycloak group with its role children as sub-groups, and every
  tenant OU MUST appear as a sub-group of its application group.
- [x] The OIDC `groups` claim with `full.path=true` MUST emit paths
  that reflect the LDAP hierarchy. Example path shapes:

  ```
  /roles/web-app-nextcloud/administrator
  /roles/web-app-wordpress/<tenant_id>/<role_name>
  /roles/web-app-wordpress/network-administrator
  ```

  Consumer code (notably the WordPress mu-plugin, but also any app
  that consumed the flat `web-app-*-<role>` claim entries before) MUST
  parse these path-shaped values. The mu-plugin's legacy flat-prefix
  matching (`web-app-wordpress-<role>`) MUST be removed as part of
  this requirement.
- [x] The `groups` client scope from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  MUST continue to be a **default** client scope on every OIDC client
  that needs group-based RBAC. Making it optional again would
  reintroduce the userinfo regression that
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  fixed and break all role mapping silently.

### WordPress mu-plugin behavior

- [x] The mu-plugin
  [infinito-oidc-rbac-mapper.php](../../roles/web-app-wordpress/files/mu-plugins/infinito-oidc-rbac-mapper.php)
  MUST be updated to parse the hierarchical group path
  `/roles/web-app-wordpress/...` in both Single-Site and Multisite. In
  Single-Site the mapper MUST treat
  `/roles/web-app-wordpress/<role_name>` entries as the source of the
  WP role, with the same highest-privilege-wins rule from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  (`administrator > editor > author > contributor > subscriber`).
- [x] The mu-plugin MUST detect Multisite at runtime (`is_multisite()`).
  In Multisite it MUST consume only entries of the form
  `/roles/web-app-wordpress/<tenant_id>/<role_name>` for per-site role
  derivation, plus `/roles/web-app-wordpress/network-administrator`
  for the network-wide super-admin.
- [x] For each site in the network (`get_sites()`), the mu-plugin MUST
  map the site to a tenant identifier via the site's canonical
  domain. Derivation of the per-site role MUST use the highest-
  privilege-wins rule, restricted to the claim entries that match
  that site's tenant.
- [x] When the user has at least one `/roles/web-app-wordpress/<tenant_id>/<role_name>`
  entry for a site and is not yet a registered member of that site,
  the mu-plugin MUST call `add_user_to_blog($blog_id, $user_id,
  $role)`.
- [x] When the user has no matching claim entry for a site and was
  previously added to that site by this mu-plugin (tracked via a
  dedicated user-meta marker), the mu-plugin MUST call
  `remove_user_from_blog()` for that site. Users added through
  channels other than this mapper MUST NOT be touched. Failure to
  respect this ownership marker risks removing operators who were
  intentionally added outside the OIDC flow.
- [x] When
  `/roles/web-app-wordpress/network-administrator` is in the claim,
  the mu-plugin MUST call `grant_super_admin($user_id)`. When it is
  not, the mu-plugin MUST call `revoke_super_admin($user_id)` so
  revocations in Keycloak propagate on the next login.
- [x] The fallback semantic from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  MUST hold per site: a user who is a registered member of a site but
  matches no per-site claim entry MUST be set to `subscriber` on that
  site, never silently elevated.

### Idempotency and safety

- [x] Running the OIDC login flow multiple times in a row MUST
  converge to the same network-wide state: no duplicate site
  memberships, no role drift, no repeated `grant_super_admin` /
  `revoke_super_admin` side effects observable to users.
- [x] The provisioning pipeline MUST NOT remove DNs that are still
  referenced by active Keycloak group memberships without first
  confirming no bound users remain. The current `ldapadd`/`ldapmodify`-
  only behavior from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  already satisfies this; the one-time migration described under
  "Migration" below is the single exception and MUST be driven
  explicitly by the migration script, not by the regular provisioning
  pass.

### Migration from the flat layout

- [x] A migration task MUST be added to
  [svc-db-openldap](../../roles/svc-db-openldap/) that runs once per
  host during the first deploy after this requirement lands, detects
  any surviving flat `cn=<application_id>-<role_name>,ou=roles,...`
  DNs, and rewrites each one to its new hierarchical DN while
  preserving its members (`memberUid`, `member`) and `gidNumber`.
- [x] The migration task MUST be idempotent: running it a second time
  MUST detect that no flat DNs remain and MUST NOT re-run the rewrite
  logic. Re-running after a partial failure MUST converge cleanly.
- [x] Immediately after the DN rewrite, the migration MUST force-
  terminate every active Keycloak user session in the affected realm
  (via `POST /admin/realms/<realm>/logout-all`, the `kcadm logout-all`
  command, or an equivalent Ansible step). Without this forced
  logout, users keep old access tokens whose `groups` claim still
  contains pre-005 flat paths (`/roles/web-app-*-<role>`) until the
  token naturally expires, which can leave them with stale
  capabilities on the new hierarchical tree for the whole token
  lifetime. The forced logout is a one-time cost at migration time
  and MUST NOT be part of the regular provisioning pass.
- [x] Consumer-side impact MUST be surveyed and updated in the same
  requirement: every place in the code base that hard-codes the old
  flat pattern (Keycloak LDAP mapper config, role-specific bind
  filters, tests, docs) MUST be migrated to the new per-application
  DN or to the new Keycloak group path. Callsites that compute an
  OIDC group path MUST use the new `rbac_group_path` lookup plugin
  described above and MUST NOT rebuild the path with inline
  `path_join` or string concatenation. A grep for
  `<application_id>-<role_name>`-shaped string literals, and for the
  `[RBAC.GROUP.NAME, ...] | path_join` idiom, MUST return zero
  production hits after the migration lands. Documentation and
  changelog entries that describe the historical flat pattern MAY
  keep the old string for archival reasons and MUST then be clearly
  marked as historical.

### Verification

- [x] The existing Playwright suite in
  [web-app-wordpress](../../roles/web-app-wordpress/) covering
  subscriber, editor, and administrator on Single-Site MUST continue
  to pass, with the only spec-side change being the switch from the
  `web-app-wordpress-<role>` group name to the hierarchical
  `/roles/web-app-wordpress/<role>` group path when joining biber to
  a group via the Keycloak admin UI.
- [x] A new Multisite Playwright spec MUST exercise a three-site
  network with three distinct canonical domains. It MUST cover:
  - A user who is assigned editor on site A and subscriber on site B
    only, and verify they have zero access to site C.
  - A user who holds
    `/roles/web-app-wordpress/network-administrator` and verify
    super-admin capabilities on all sites via
    `/wp-admin/network/users.php`.
  - Revocation: remove the network-administrator group in Keycloak
    and verify that on the next login the user loses super-admin on
    every site.
- [x] The Multisite spec MUST follow the same idempotency contract
  as the spec from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md):
  starting memberships of the test user MUST be preserved after a
  full run; additions made by the test MUST be reverted; pre-existing
  memberships MUST NOT be removed. Keycloak admin UI is mandated only
  for the add step; teardown MAY use the Keycloak Admin REST API for
  determinism.
- [x] A unit-level test in
  [test_build_ldap_role_entries.py](../../tests/unit/roles/svc-db-openldap/test_build_ldap_role_entries.py)
  MUST cover both layouts in the same run: a non-tenant app
  (post-migration layout, no tenant OU) and a domain-tenant app with
  mixed `per_tenant` and `global` roles, asserting the exact DN set
  each produces.
- [x] A unit-level test MUST cover the migration task on a synthetic
  LDIF fixture that contains flat pre-005 entries and assert that the
  task produces exactly the expected hierarchical DNs while
  preserving group members.
- [x] The existing Playwright spec
  [playwright.spec.js](../../roles/web-app-yourls/files/playwright.spec.js)
  in [web-app-yourls](../../roles/web-app-yourls/) MUST verify the
  new RBAC layout end to end for a non-tenant single-role app. YOURLS
  is the smallest meaningful consumer of the scheme: it has one
  administrator role, guards `/admin/` via oauth2-proxy's
  `allowed_groups`, and is structurally representative of every
  non-tenant role that opts into `rbac`. The spec MUST assert that:
  - The Keycloak group path `/roles/web-app-yourls/administrator`
    exists after deploy and carries the administrator user.
  - A user who holds that group membership can reach the admin area
    behind the oauth2-proxy, and a user who does not MUST be blocked
    by oauth2-proxy, so the new layout is proven to flow through the
    `allowed_groups` config end to end.
  - The pre-005 flat Keycloak group path
    `/roles/web-app-yourls-administrator` is no longer referenced in
    the role's `allowed_groups` config; the spec MUST fail if any
    production artefact still carries that string.
  - Baseline MUSTs (CSP, OIDC round-trip, logged-out final state) keep
    holding, matching the contract the spec already enforces today.

### Backwards compatibility

- [x] The migration described under "Migration from the flat layout"
  replaces the "no migration needed" clause of
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md).
  Operators upgrading from 004 to 005 MUST run the standard deploy
  playbook, which MUST pick up the migration task automatically. No
  manual LDIF editing MAY be required.
- [x] Consumer apps whose code hard-codes the flat
  `cn=<application_id>-<role_name>,ou=roles,...` pattern MUST be
  updated in this requirement, in the same commit sequence as the
  provisioning change, so the tree is never in a mixed state in a
  deployed environment.

### Documentation

The project has two documentation SPOTs for this topic: a **design SPOT**
for contributors and role maintainers under `docs/contributing/design/iam/`,
and an **administration SPOT** for operators under
`docs/administration/configuration/`. Every documentation item below MUST
follow [documentation.md](../contributing/documentation.md) (RFC 2119
keywords, link-text rules, emojis after headings, no em dashes, English
prose).

- [x] A new page `docs/contributing/design/iam/rbac.md` MUST be created
  as the **design SPOT** for RBAC. It MUST cover:
  - The LDAP layout contract: the `ou=<application_id>,ou=roles,...`
    pattern for every role with an `rbac:` block, the tenant OU layer
    for tenant-aware roles, and the explicit ban on the pre-005 flat
    `cn=<application_id>-<role_name>,ou=roles,...` pattern.
  - The `rbac.tenancy` schema (`axis`, `source`, per-role `scope`) and
    the decision rule for when an application SHOULD opt in.
  - The `rbac_group_path` lookup plugin as the **only** sanctioned
    way to compute an OIDC group path for a role: contract, examples,
    failure modes. The page MUST state that inline
    `[RBAC.GROUP.NAME, ...] | path_join` MUST NOT be used and explain why
    centralising the path computation protects against partial
    migrations when the layout evolves again.
  - The Keycloak group tree that mirrors the LDAP OUs, the default
    `groups` client scope contract from
    [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md),
    and the OIDC claim path shape consumers MUST parse.
  - A short cross-link to the existing
    [common.md](../contributing/design/iam/common.md),
    [ldap.md](../contributing/design/iam/ldap.md), and
    [oidc.md](../contributing/design/iam/oidc.md) so a reader lands on
    the right SPOT no matter which facet of IAM they approach first.
  - No step-by-step operator instructions. Those belong in the
    administration SPOT described below.
- [x] A new page `docs/administration/configuration/rbac.md` MUST be
  created as the **administration SPOT** for RBAC. It MUST cover:
  - How an operator assigns a Keycloak group (or LDAP membership) to a
    user so the user gains a given WordPress role, including
    per-tenant assignments for Multisite and the separate
    `network-administrator` group.
  - How the OIDC `groups` claim reaches the application and what the
    operator can check in Keycloak when a user ends up with the
    fallback `subscriber` role.
  - A pointer to the one-time migration task from the "Migration from
    the flat layout" section above: what it does, how to verify it
    ran, and how to roll back if needed.
  - A single "See also" link to
    [rbac.md](../contributing/design/iam/rbac.md) for readers who need
    the underlying design rationale. The administration SPOT MUST NOT
    duplicate design prose; it MUST defer to the design SPOT for the
    "why" and only cover the "how".
- [x] [mu-plugins/README.md](../../roles/web-app-wordpress/files/mu-plugins/README.md)
  MUST be updated to describe the new per-application group-path
  parsing: for Single-Site
  (`/roles/web-app-wordpress/<role>`), for Multisite
  (`/roles/web-app-wordpress/<tenant_id>/<role>`), and the separate
  network-administrator path. It MUST also describe the ownership
  marker that prevents the mu-plugin from touching manually-added
  memberships. Readers looking for broader RBAC rules MUST be
  redirected with a "See also" link to
  [rbac.md](../contributing/design/iam/rbac.md).
- [x] The `web-app-wordpress` role `README.md` MUST gain a section
  explaining how to enable Multisite for a deployment, how to declare
  the per-site canonical domains that drive the tenant OU hierarchy,
  and how to assign the `web-app-wordpress/network-administrator`
  Keycloak group. For the operator-facing day-two steps this section
  MUST link to
  [rbac.md](../administration/configuration/rbac.md) instead of
  inlining them.
- [x] The rules for the new `ou=<application_id>,ou=roles,...` layout
  and for `rbac.tenancy` MUST land in the design SPOT
  (`docs/contributing/design/iam/rbac.md`) and MUST NOT be duplicated
  in per-role README files. Per-role READMEs MAY briefly state that a
  role opts in to tenancy and MUST link to the design SPOT for the
  contract.
