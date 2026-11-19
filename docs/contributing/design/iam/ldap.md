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
| `LDAP.SERVER.SOCKET_URI` | `ldapi://` URI of the socket OpenLDAP binds into its volumes directory, for host-side clients on the OpenLDAP node in either mode, since swarm publishes no local port. The Playwright runner gets it as `LDAP_URL` and mounts the socket directory read-only only for a role whose `templates/playwright.env.j2` renders `LDAP_URL`, while `STACK_HOST` is a host of `svc-db-openldap` |
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
| Auxiliary | `INFINITO_USER` | `infinitoUser` | Allows the profile attributes `inetOrgPerson` lacks: `c`, the phonetic names and the time zone |
| Auxiliary | `INFINITO_MAILBOX_USER` | `infinitoMailboxUser` | Allows the secondary address of the `mailbox` email policy; attached to user entries and required by the Keycloak federation only under that policy |

Each entry has exactly one structural class chain.
New auxiliary classes SHOULD be added under `LDAP.USER.OBJECTS.AUXILIARY` so consumers can probe them by symbolic name instead of literal string.
Keycloak's `userObjectClasses` lists every auxiliary class it requires, and its LDAP federation finds only entries that hold all of them, so a class MUST be attached to every existing entry before Keycloak requires it.

## User Attributes 🪧

`LDAP.USER.ATTRIBUTES` lists the LDAP attribute names that applications query:

| Key | Default value | Meaning |
|---|---|---|
| `LDAP.USER.ATTRIBUTES.ID` | `uid` | Login identifier, paired with the OIDC `preferred_username` |
| `LDAP.USER.ATTRIBUTES.MAIL` | `mail` | Primary email, seeded once from the inventory and never overwritten by a deploy; `<uid>@<DOMAIN_PRIMARY>` under the `mailbox` email policy |
| `LDAP.USER.ATTRIBUTES.SECONDARY_MAIL` | `infinitoSecondaryMail` | Secondary email under the `mailbox` email policy, Keycloak's `email` field, seeded once and never overwritten by a deploy |
| `LDAP.USER.ATTRIBUTES.FULLNAME` | `cn` | Display name |
| `LDAP.USER.ATTRIBUTES.FIRSTNAME` | `givenName` | First name |
| `LDAP.USER.ATTRIBUTES.SURNAME` | `sn` | Last name |
| `LDAP.USER.ATTRIBUTES.DISPLAY_NAME` | `displayName` | Preferred display name, Keycloak `nickname` |
| `LDAP.USER.ATTRIBUTES.INITIALS` | `initials` | Middle name, Keycloak `middleName` |
| `LDAP.USER.ATTRIBUTES.PHONE` | `telephoneNumber` | Phone number, Keycloak `phoneNumber` |
| `LDAP.USER.ATTRIBUTES.MOBILE` | `mobile` | Mobile number, Keycloak `phoneNumberAlt` |
| `LDAP.USER.ATTRIBUTES.STREET` | `street` | Street address |
| `LDAP.USER.ATTRIBUTES.POSTAL_CODE` | `postalCode` | Postal code, Keycloak `postal_code` |
| `LDAP.USER.ATTRIBUTES.LOCALITY` | `l` | City, Keycloak `locality` |
| `LDAP.USER.ATTRIBUTES.REGION` | `st` | State or region, Keycloak `region` |
| `LDAP.USER.ATTRIBUTES.COUNTRY` | `c` | ISO 3166-1 alpha-2 country code |
| `LDAP.USER.ATTRIBUTES.ORGANIZATION` | `o` | Organization, Keycloak `institution` |
| `LDAP.USER.ATTRIBUTES.DEPARTMENT` | `ou` | Department |
| `LDAP.USER.ATTRIBUTES.TITLE` | `title` | Job title |
| `LDAP.USER.ATTRIBUTES.DESCRIPTION` | `description` | Free-text description |
| `LDAP.USER.ATTRIBUTES.EMPLOYEE_NUMBER` | `employeeNumber` | Personnel number, Keycloak `idNumber` |
| `LDAP.USER.ATTRIBUTES.WEBSITE` | `labeledURI` | Website |
| `LDAP.USER.ATTRIBUTES.LOCALE` | `preferredLanguage` | Preferred language |
| `LDAP.USER.ATTRIBUTES.TIMEZONE` | `infinitoTimezone` | IANA time zone, Keycloak `zoneinfo` |
| `LDAP.USER.ATTRIBUTES.PHONETIC_GIVEN` | `infinitoNamePhoneticGiven` | Phonetic first name |
| `LDAP.USER.ATTRIBUTES.PHONETIC_FAMILY` | `infinitoNamePhoneticFamily` | Phonetic last name |
| `LDAP.USER.ATTRIBUTES.PHOTO` | `jpegPhoto` | Avatar, read by applications from the directory only |
| `LDAP.USER.ATTRIBUTES.SSH_PUBLIC_KEY` | `sshPublicKey` | SSH key attribute |
| `LDAP.USER.ATTRIBUTES.NEXTCLOUD_QUOTA` | `nextcloudQuota` | Per-user Nextcloud quota |
| `LDAP.USER.ATTRIBUTES.MEMBER_OF` | `memberOf` | Role groups of a user, maintained by the memberof overlay |
| `LDAP.USER.ATTRIBUTES.PASSWORD` | `userPassword` | Password hash |

Keycloak maps every profile attribute through `KEYCLOAK_PROFILE_ATTRIBUTES` in [main.yml](../../../../roles/web-app-keycloak/vars/main.yml): one `profile:<name>` LDAP mapper and one user-profile field per entry. Contact fields are editable by the user, organization fields only by administrators. The standard OIDC claims follow from Keycloak's built-in `profile`, `phone` and `address` scopes, so an application requests `phone` or `address` when it consumes those claims.

The inventory `email` of a user reaches `mail` only while the entry holds no `mail`. Editing it in the inventory changes nothing for an existing user; change the address in Keycloak or in the directory instead. See [svc-db-openldap](../../../../roles/svc-db-openldap/README.md#email-addresses) for the mailbox layout.

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
| `LDAP.RBAC.MEMBER_ATTRIBUTE` | Membership attribute of a role group, `member` |
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
