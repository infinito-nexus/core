# RBAC 🛂

This page is the design SPOT for the Infinito.Nexus RBAC layer that provisions LDAP groups, synchronises them to Keycloak, and emits them as the OIDC `groups` claim. For IAM fundamentals that span both providers, see [common.md](common.md). For the LDAP server layer, see [ldap.md](ldap.md). For the OIDC client layer, see [oidc.md](oidc.md). Operator-facing steps live in [Administration RBAC](../../../administration/configuration/rbac.md).

## LDAP layout contract 🌳

Every role that declares RBAC at the file root of its `meta/rbac.yml` (per [req-008](../../../requirements/008-role-meta-layout.md)) MUST be provisioned with a per-application namespace under the container named by `RBAC.GROUP.NAME` (default `roles`). Each LDAP group entry is a direct child of that container; the application identifier (and the tenant identifier, if any) is encoded into the CN with hyphen separators:

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
    source: "server.domains.canonical"    # Jinja path, only "server.domains.canonical" is implemented
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

The Keycloak group tree is built by **per-application** `group-ldap-mapper`s. Each deployed application gets one mapper anchored at `/roles/<application_id>` whose LDAP filter `(&(objectClass=groupOfNames)(cn=<application_id>-*))` surfaces only that application's role groups. The mapper uses the LDAP `description` attribute as the visible Keycloak group name, so the resulting group paths carry no redundant prefix.

A shared mapper that imports every LDAP group with `preserve.group.inheritance=true` MUST NOT be used. Role names recur across applications (`administrator`, `editor`, ...) and Keycloak's `GroupTreeResolver` keys its lookup map on the group name, so the second `administrator` silently overwrites the first.

The `groups` client scope emits the OIDC `groups` claim with `full.path=true`, so consumers receive entries shaped like:

```
/roles/web-app-nextcloud/administrator
/roles/web-app-wordpress/<tenant>/<role>
/roles/web-app-wordpress/network-administrator
```

The scope MUST be a **default** client scope on every OIDC client that needs group-based RBAC. Making it optional again reintroduces the userinfo regression that requirement 004 fixed: when optional with `include.in.token.scope=false`, Keycloak drops the group-membership mapper from userinfo even when the scope is explicitly requested, so consumers receive no groups and fall back to `subscriber`.

## See also 🔗

- [common.md](common.md)
- [ldap.md](ldap.md)
- [oidc.md](oidc.md)
- [Administration RBAC](../../../administration/configuration/rbac.md)
