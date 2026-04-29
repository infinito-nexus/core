# RBAC 🛂

This page is the administration SPOT for granting and revoking application role memberships via Keycloak. It covers the **how**; for the **why** (design, schema, LDAP layout, client-scope contract) see [RBAC design](../../contributing/design/iam/rbac.md).

## Granting a role 🎟️

Every application role corresponds to one Keycloak group whose path is hierarchical:

```
# single-site app
/roles/<application_id>/<role_name>

# Multisite (tenant-aware) app, per-site role
/roles/<application_id>/<tenant>/<role_name>

# Multisite (tenant-aware) app, network-wide role
/roles/<application_id>/network-administrator
```

To grant a user the role `<role_name>` on `<application_id>`:

1. Log in to the Keycloak admin console as the platform super administrator.
2. Switch to the configured realm (for example `infinito.nexus`).
3. Open **Users**, search for the user, and select them.
4. Open the **Groups** tab on the user profile.
5. Click **Join Group**, search for the target role name, and join the group at the full path shown above.

To revoke a role, remove the user from the same group. Changes take effect the next time the user completes an OIDC sign-in; no immediate logout is required for the user to retain their current session's capabilities.

## Confirming the `groups` claim 🧾

When a user unexpectedly ends up in the fallback `subscriber` role, check the following in order:

1. The user is a direct member of the expected group (not only a parent OU).
2. The OIDC client used by the application has the `groups` client scope attached as a **default** scope (not optional). The design note in [RBAC design](../../contributing/design/iam/rbac.md) explains why.
3. The Keycloak **Userinfo** preview for the user contains a `groups` array with the full path. If it does not, the scope is not reaching the userinfo endpoint and the mapping will not fire.

## Migration from the pre-005 flat layout 🔁

Infinito.Nexus before requirement 005 provisioned all RBAC groups flat under `ou=roles` with names shaped `<application_id>-<role_name>`. The 005 deploy rewrites these DNs into the hierarchical layout described above, keeps every `memberUid` / `member`, and forces a Keycloak **Logout all** so no stale access tokens keep pre-005 paths alive. The migration runs automatically as part of `svc-db-openldap` provisioning; no manual LDIF editing is required.

If you need to roll back the migration, restore the LDAP backup taken before the first deploy that included requirement 005 and also invalidate the affected Keycloak sessions.

## See also 🔗

- [RBAC design](../../contributing/design/iam/rbac.md)
