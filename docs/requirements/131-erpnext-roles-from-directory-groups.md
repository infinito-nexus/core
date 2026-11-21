# 131 - ERPNext Roles from Directory Groups for Consumer Roles

## User Story

As a platform operator, I want ERPNext to grant the ERPNext roles a consumer role declares to the members of its RBAC groups, so that staff of a custom role such as the security check get their ERPNext role on sign-in instead of by hand.

## Context (2026-11-14, drafted by Security against 067)

The security check (infinito-nexus/security, requirement 004) needs its administrators to hold the ERPNext role `Security Check Editor`. Core has no mapping from a directory group to an ERPNext role that a consumer can extend: `ERPNEXT_OIDC_GROUP_ROLE_MAP` does not exist, and [067](067-erpnext-structure-coordination.md) (decisions 2 and 5, with its reserved-prefix lint) keeps every security-check name out of `roles/web-app-erpnext`. Decision 2 of 067 places the RBAC role mapping in the core role as all-tenant structure, and decision 4 limits every change to directory-owned accounts. This requirement makes that mapping open to consumers without naming any of them in the core role.

## Decisions

1. **Inventory key.** `applications.web-app-erpnext.services.erpnext.group_roles` is an inventory list of entries `{group: <RBAC group path>, roles: [<ERPNext role>, ...]}`. It defaults to an empty list. A consumer declares its entries in the inventory, the same way it declares `api_bot.extra_roles` (067 decision 3).
2. **Where it applies.** The core role reconciles the mapping on every sign-in through Keycloak or LDAP and in the RBAC sync, for directory-owned accounts only (067 decision 4).
3. **What it changes.** A member of a mapped group gets every mapped role it lacks. A former member loses only the roles the mapping granted, never a role granted outside the mapping. A mapped role the site lacks is created as an empty Role first (067 decision 3).
4. **No consumer names in core.** The core role ships no entry; the reserved-prefix lint of 067 keeps passing.

## Acceptance Criteria

- [x] `services.erpnext.group_roles` exists in the core role's config with an empty default and is documented in the [web-app-erpnext README](../../roles/web-app-erpnext/README.md) next to `api_bot.extra_roles`.
- [x] On sign-in, a directory-owned account in a mapped group holds every mapped role afterwards; a unit test on the fake Frappe site proves it.
- [x] After the account leaves the group, the next sign-in or RBAC sync revokes the mapped roles and keeps every role granted outside the mapping; a unit test proves it with a staff account holding an unmanaged role.
- [x] A mapped role the site lacks is created as an empty Role before the grant; a unit test proves it.
- [x] Accounts that are not directory-owned (service, API, website, customer accounts) are never changed; a unit test proves it.
- [x] The reserved-prefix lint of 067 passes, and no file under `roles/web-app-erpnext` names a consumer group or role.
- [ ] A deploy with an entry `{group: /<RBAC>/web-app-cst-security-check/administrator, roles: [Security Check Editor]}` in the inventory gives a member of that group the role after sign-in, proven by a check against a deployed site.

## Cross-linking

- Builds on: [067](067-erpnext-structure-coordination.md) on the IAM line.
- Consumer: the security check declares its entry in its own role config once this lands (infinito-nexus/security requirement 004).
