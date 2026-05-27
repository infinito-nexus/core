# LDAP 📒

This page describes how application roles consume the platform's LDAP provider, [OpenLDAP](../../../../roles/svc-db-openldap/).
The variable tree lives in [12_ldap.yml](../../../../group_vars/all/12_ldap.yml) under `LDAP`.
For the cross-cutting IAM principles, including the paired identifier rule shared with OIDC, see [common.md](common.md).
For OIDC-side details see [oidc.md](oidc.md).

## Variable Tree 🌳

The high-level structure:

| Key | Meaning |
|---|---|
| `LDAP.DN.ROOT` | Base DN derived from `DOMAIN_PRIMARY` |
| `LDAP.DN.ADMINISTRATOR.DATA` | Bind DN for CRUD on entries below `ROOT` |
| `LDAP.DN.ADMINISTRATOR.CONFIGURATION` | Bind DN for `cn=config` schema work |
| `LDAP.DN.OU.USERS` | Container for user objects |
| `LDAP.DN.OU.GROUPS` | Container for organizational groups |
| `LDAP.DN.OU.ROLES` | Container for application RBAC roles |
| `LDAP.BIND_CREDENTIAL` | Password for the data administrator DN |
| `LDAP.SERVER.DOMAIN` | Hostname or container name to dial |
| `LDAP.SERVER.PORT` | Port resolved through the ports registry |
| `LDAP.SERVER.URI` | Full `ldap[s]://host:port` URI |
| `LDAP.SERVER.SECURITY` | Transport security mode, empty when unused |
| `LDAP.NETWORK.LOCAL` | True when the consumer shares the OpenLDAP Docker network |

Rules:

- Roles MUST connect via `LDAP.SERVER.URI`. Building the URI from the
  individual `INFINITO_DOMAIN`, `PORT`, and protocol parts is forbidden because the
  helper variables in [12_ldap.yml](../../../../group_vars/all/12_ldap.yml)
  already pick the correct scheme based on Docker-network availability.
- The data administrator DN MUST be used for adding, modifying, and removing
  users, groups, and roles. The configuration administrator DN MUST be used
  only for schema and overlay changes pushed via `ldapi:///`.
- New OUs SHOULD NOT be invented. Place users under `OU.USERS`, RBAC roles
  under `OU.ROLES`, and organizational groups under `OU.GROUPS`.

## Object Classes 🧱

`LDAP.USER.OBJECTS` lists the structural and auxiliary object classes attached to user entries:

| Group | Key | Default | Purpose |
|---|---|---|---|
| Structural | (list) | `person`, `inetOrgPerson`, `posixAccount` | Core identity, internet attributes, UNIX account fields |
| Auxiliary | `NEXTCLOUD_USER` | `nextcloudUser` | Adds `nextcloudQuota` and `nextcloudEnabled` |
| Auxiliary | `SSH_PUBLIC_KEY` | `ldapPublicKey` | Stores SSH public keys for services like Gitea |

Each entry has exactly one structural class chain.
New auxiliary classes SHOULD be added under `LDAP.USER.OBJECTS.AUXILIARY` so consumers can probe them by symbolic name instead of literal string.

## User Attributes 🪧

`LDAP.USER.ATTRIBUTES` lists the LDAP attribute names that applications query:

| Key | Default value | Meaning |
|---|---|---|
| `LDAP.USER.ATTRIBUTES.ID` | `uid` | Login identifier, paired with the OIDC `preferred_username` |
| `LDAP.USER.ATTRIBUTES.MAIL` | `mail` | Primary email |
| `LDAP.USER.ATTRIBUTES.FULLNAME` | `cn` | Display name |
| `LDAP.USER.ATTRIBUTES.FIRSTNAME` | `givenName` | First name |
| `LDAP.USER.ATTRIBUTES.SURNAME` | `sn` | Last name |
| `LDAP.USER.ATTRIBUTES.SSH_PUBLIC_KEY` | `sshPublicKey` | SSH key attribute |
| `LDAP.USER.ATTRIBUTES.NEXTCLOUD_QUOTA` | `nextcloudQuota` | Per-user Nextcloud quota |

Rules:

- Templates MUST reference `LDAP.USER.ATTRIBUTES.*`. Hardcoded `uid`, `cn`,
  or `sn` values are forbidden because the underlying schema may switch
  flavor in the future.
- The login attribute is paired with the OIDC username claim by design.
  Changing one without the other breaks LDAP-OIDC correlation. See
  [oidc.md](oidc.md) for the OIDC-side rule.

## Filters 🔎

`LDAP.FILTERS.USERS` provides reusable LDAP search filters:

| Key | Purpose |
|---|---|
| `LDAP.FILTERS.USERS.LOGIN` | Resolve a single user by login attribute, parameterized via `%uid` |
| `LDAP.FILTERS.USERS.ALL` | Match every user entry, used for sync jobs and listings |

Roles SHOULD prefer these filters over composing new ones inline so a future schema change updates every consumer at once.

## RBAC 👥

`LDAP.RBAC` controls how application roles are represented:

| Key | Meaning |
|---|---|
| `LDAP.RBAC.FLAVORS` | Allowed group flavors, currently `groupOfNames` |
| `LDAP.RBAC.EMPTY_MEMBER_DN` | Placeholder DN for empty `groupOfNames` groups |

`groupOfNames` requires at least one `member` attribute.
The placeholder DN exists so newly created empty groups remain schema-valid until the first real member is added.

## Related Files 📚

| File | Purpose |
|---|---|
| [12_ldap.yml](../../../../group_vars/all/12_ldap.yml) | LDAP SPOT, defines `LDAP.*` |
| [svc-db-openldap](../../../../roles/svc-db-openldap/) | LDAP provider role |
| [oidc.md](oidc.md) | OIDC-side counterpart, paired user identifier |
| [common.md](common.md) | Cross-cutting IAM principles and integration checklist |
