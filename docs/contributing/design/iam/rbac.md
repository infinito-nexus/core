# RBAC 🛂

This page describes the design of the Infinito.Nexus RBAC layer that provisions LDAP groups, synchronises them to Keycloak, and emits them as the OIDC `groups` claim.
For IAM fundamentals that span both providers, see [common.md](common.md).
For the LDAP server layer, see [ldap.md](ldap.md).
For the OIDC client layer, see [oidc.md](oidc.md).
Operator-facing steps live in [Administration RBAC](../../../administration/configuration/rbac.md).

## LDAP layout contract 🌳

Every role that declares RBAC at the file root of its `meta/rbac.yml` MUST be provisioned with a per-application namespace under the container named by `RBAC.GROUP.NAME` (default `roles`). Each LDAP group entry is a direct child of that container; the application identifier (and the tenant identifier, if any) is encoded into the CN with hyphen separators:

```
cn=<application_id>-<role_name>,ou=roles,<LDAP_DN_BASE>                       # non-tenant / global role
cn=<application_id>-<tenant_id>-<role_name>,ou=roles,<LDAP_DN_BASE>           # tenant-aware per-tenant
cn=<application_id>-<role_name>,ou=roles,<LDAP_DN_BASE>                       # tenant-aware scope=global
```

The producer [build_ldap_role_entries](../../../../roles/svc-db-openldap/filter_plugins/build_ldap_role_entries.py) also emits a per-application `groupOfNames` container `cn=<application_id>,ou=roles,...` whose `member` attribute references every role group of that application, so an LDAP-only consumer can still navigate the hierarchy. Keycloak does not rely on those containers; it reconstructs `/roles/<application_id>/<role_name>` via per-application mappers (see below).

## `rbac.tenancy` schema 📐

```yaml
rbac:
  tenancy:
    axis:   "domain"                      # one of: "none" (default), "domain"
    source: "domains.canonical"    # Jinja path, only "domains.canonical" is implemented
  roles:
    <role_name>:
      description: "..."
      scope:  "per_tenant"                # one of: "per_tenant" (default), "global"
```

An application SHOULD opt in to `axis: domain` only when its authorisation model is genuinely per-tenant and the tenant axis is the canonical domain. Typical consumer: WordPress Multisite. Applications whose authorisation is one global user set (Nextcloud, Gitea, Keycloak itself) MUST keep `axis: none`.

## `rbac_group_path` lookup plugin 🧭

[rbac_group_path](../../../../plugins/lookup/rbac_group_path.py) is the **only** sanctioned way to derive the OIDC group path for an application role. Consumers MUST call it:

```jinja
# non-tenant app
"{{ lookup('rbac_group_path', application_id='web-app-yourls', role='administrator') }}"
# -> "roles/web-app-yourls/administrator"

# tenant-aware, per-tenant role
"{{ lookup('rbac_group_path', application_id='web-app-wordpress',
           role='editor', tenant='blog.example') }}"
# -> "roles/web-app-wordpress/blog.example/editor"

# tenant-aware, scope=global role
"{{ lookup('rbac_group_path', application_id='web-app-wordpress',
           role='network-administrator') }}"
# -> "roles/web-app-wordpress/network-administrator"
```

Inline `[RBAC.GROUP.NAME, ...] | path_join` MUST NOT be used: it scatters the path shape across dozens of files and makes future layout changes partial. Centralising the path in the plugin guarantees that a layout evolution stays a one-file change.

## Keycloak group tree and the `groups` client scope 🎫

The Keycloak group tree is built by **per-application** `group-ldap-mapper`s. Each deployed application gets one mapper anchored at `/roles/<application_id>` whose LDAP filter `(&(objectClass=groupOfNames)(|(cn=<application_id>-<role>)...))` lists each of that application's role groups by its exact `cn`, so an application whose id prefixes another one (`svc-net-tor` and `svc-net-tor-smtp`) never sees the other's groups. The mapper uses the LDAP `description` attribute as the visible Keycloak group name, so the resulting group paths carry no redundant prefix.

A shared mapper that imports every LDAP group with `preserve.group.inheritance=true` MUST NOT be used. Role names recur across applications (`administrator`, `editor`, ...) and Keycloak's `GroupTreeResolver` keys its lookup map on the group name, so the second `administrator` silently overwrites the first.

The `groups` client scope emits the OIDC `groups` claim with `full.path=true`, so consumers receive entries shaped like:

```
/roles/web-app-nextcloud/administrator
/roles/web-app-wordpress/<tenant>/<role>
/roles/web-app-wordpress/network-administrator
```

The scope MUST be a **default** client scope on every OIDC client that needs group-based RBAC.
Making it optional reintroduces a userinfo regression: when optional with `include.in.token.scope=false`, Keycloak drops the group-membership mapper from userinfo even when the scope is explicitly requested, so consumers receive no groups and fall back to `subscriber`.

## Access policy 🚪

Every role picks one of two access shapes:

| Shape | Gate | In-app role |
|---|---|---|
| Open | No `oauth2.allowed_groups`; every realm user signs in | The lowest native role, raised by the role groups the user holds |
| Restricted | `oauth2.allowed_groups` lists every declared role path, built with `rbac_group_path` | Mapped from the role group that let the user in |

Collaboration, publishing, learning and community applications are open. Back-office, infrastructure, AI and single-owner applications are restricted, and a restricted role that has a regular user tier declares a `user` role next to the implicit `administrator`.

## Mapping roles into an application 🔁

A role maps groups at login when the application reads the `groups` claim, an LDAP group filter or a SAML attribute. When the free edition offers none of these, the role reconciles at deploy time through [members.yml](../../../../tasks/utils/rbac/members.yml):

```yaml
- include_tasks: utils/rbac/members.yml
  vars:
    rbac_members_application_id: "{{ application_id }}"
    rbac_members_role: administrator
```

It sets `rbac_members` to the `{username, email}` list of the role group. With OpenLDAP deployed the list comes from `memberOf` in the directory, so memberships changed in the Keycloak admin console count; without it, from the inventory grants. A reconciler MUST promote every member and demote every account outside the group, except the bootstrap and break-glass accounts the role provisions itself.

An application that reads its roles from `realm_access.roles` instead of the groups claim sets `realm_roles: true` in its `meta/rbac.yml`. [10_realm_role_grants.yml](../../../../roles/web-app-keycloak/tasks/update/10_realm_role_grants.yml) then creates one realm role `<application_id>-<role>` per declared role, `administrator` included, and grants it to the matching group. Every realm user also holds `default-roles-<realm>`, which the application can map to its lowest role so that nobody without a role group is locked out.

## Hosts for role members 🏠

An application gives every member of one of its roles a host below a parent domain by declaring `domains.served` next to `canonical`:

```yaml
domains:
  served:
    - parent: user.blog.{{ DOMAIN_PRIMARY }}
      role: site-owner
```

[served.py](../../../../utils/domains/served.py) resolves the declaration once per play into `CURRENT_PLAY_SERVED_DOMAINS`. Where `wildcard_certificate_available` in [tls/common.py](../../../../utils/tls/common.py) holds for the application, the play serves one name `*.<parent>`; elsewhere it serves `<username>.<parent>` for every inventory user holding the role. A member is served only when `is_member_label` accepts the username. When every domain of the application lies on Tor, as on a tor-only node, `served_parent` swaps the parent for its onion sibling, so the names and the `parents` the lookup returns follow the canonical domains onto the hidden service, which routes every `<label>.<node>.onion` by its `Host` header. The constructor never fails on a declaration or a member; [served_domains](../../../../plugins/lookup/served_domains.py) also returns the problems, and the declaring role fails on its own. The `tls` and `cert` lookups resolve the served names to their application, the front proxy probes a wildcard name through the host `infinito-probe.<parent>`, and `CURRENT_PLAY_DOMAINS_ALL` carries them into certificates and DNS. `lookup('domains')`, tenancy and `domains.canonical` never contain them, so Keycloak registers no redirect URI for them.

## Keycloak admin console 🖥️

[web-app-keycloak](../../../../roles/web-app-keycloak/meta/rbac.yml) declares `user-manager`, `auditor` and `impersonator`, each with the `realm-management` client roles it carries under `realm_management`. [09_console_rbac.yml](../../../../roles/web-app-keycloak/tasks/update/09_console_rbac.yml) grants those roles to each group after the per-app mapper resync. A role with a non-empty `realm_management` list counts as an administrator role, so only a platform administrator may grant it through the [access-request service](../../../../roles/web-svc-access-request/README.md). `KEYCLOAK_RBAC_RUN_APP_IDS` always contains `web-app-keycloak`, so every run of the role provisions these groups, also an update whose `APPLICATIONS_WHITELIST` names only other applications. `realm-admin` is never granted to a group; the local bootstrap account keeps it.

## Header-trust roles 🪪

These roles log a user in from an identity header that openresty sets after oauth2-proxy verified the session. Openresty is the trust boundary: every proxying location blanks the headers listed in `TRUSTED_IDENTITY_HEADERS` of [header_trust.py](../../../../utils/roles/header_trust.py) before it sets its own, so a client cannot forge them. A published backend port bypasses that boundary, which is why these backends bind `DOCKER_BIND_HOST` and publish no `ports.local` port in swarm. A proxy secret, where present, is a second gate: the backend accepts the header only together with a secret that only openresty sends.

[header_trust.py](../../../../utils/roles/header_trust.py) detects a header-trust role from its files: any file outside docs and Playwright specs that names a trusted header in any spelling, `X_FORWARDED_PREFERRED_USERNAME` and `X-Forwarded-Access-Token` included. Each such role declares the rest under its `sso` service block in `meta/services.yml`:

```yaml
sso:
  header_trust:
    proxy_secret: sso_proxy_secret
    switch: "lookup('sso', application_id, 'is_proxy_gated')"
    files: [files/sso/header_auth.py]
```

`proxy_secret` names the `credentials` key of `meta/secrets.yml` whose value openresty sends beside the header, or is `false` when the header alone logs the user in. `switch` states what turns the trust on, `always` when the backend trusts the header whenever it runs; the lint checks only that every `services.` path it names resolves in the role's `meta/services.yml`, not that the expression is true to the code. `files` lists the files that make the backend trust the header. Each of them lies inside the role, is neither documentation nor a test or Playwright file, carries no `# nocheck: header-trust`, and names a trusted header itself or a `vars/main.yml` variable that holds one on a line that is not a comment. A file that names a header without trusting it carries `# nocheck: header-trust` with a reason in its head, and that reason is the one listed below.

The docs build renders the table between these markers; git holds them empty:

<!-- header-trust-table:begin -->
<!-- header-trust-table:end -->

Candidates that trust no header and that no file names, so neither table above lists them:

| Role | Why it trusts no header |
|---|---|
| `web-app-funkwhale` | Funkwhale signs users in against LDAP itself (`FUNKWHALE_LDAP_ENABLED`); the SSO gate only guards the front door. |
| `web-app-akaunting` | Akaunting signs users in through LDAP (`AKAUNTING_LDAP_ENABLED`) or its own OIDC login. |

[test_header_trust_declaration.py](../../../../tests/lint/ansible/roles/test_header_trust_declaration.py) fails when a detected role declares nothing, when a declaration sits on a role nothing detects, when a declaration does not resolve or names a file that trusts no header, and when a `# nocheck: header-trust` marker states no reason. [test_header_trust_table_not_committed.py](../../../../tests/lint/repository/documentation/test_header_trust_table_not_committed.py) keeps the committed block empty and the candidates above undetected.

## See also 🔗

- [common.md](common.md)
- [ldap.md](ldap.md)
- [oidc.md](oidc.md)
- [Administration RBAC](../../../administration/configuration/rbac.md)
