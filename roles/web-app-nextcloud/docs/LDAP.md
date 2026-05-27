# Add LDAP Users Manually for Immediate Sharing

In a default Nextcloud + LDAP setup, user accounts are only created in the internal Nextcloud database **after their first login**. This means that even if a user exists in LDAP, they **cannot receive shared files or folders** until they have logged in at least once, or are manually synchronized.

To make LDAP users available for sharing **without requiring initial login**, follow these steps:

## 1. Search for the User in LDAP

Check if the user exists in the configured LDAP directory:

```bash
docker exec -u www-data nextcloud php occ ldap:search <username>
```

If the user is found, proceed to the next step.

## 2. Create the User in Nextcloud from LDAP

Manually trigger a sync to register the user in the Nextcloud database:

```bash
docker exec -u www-data nextcloud php occ ldap:check-user --update <username>
```

**Example:**

```bash
docker exec -u www-data nextcloud php occ ldap:check-user --update viktoriakaffanke
```

Once executed, the user becomes fully available in the system (for sharing, group membership, and permissions) even without logging in.

## 3. Synchronize All Known Users (Optional)

To synchronize account data (display name, mail address, group memberships, etc.) for **all users** currently known to Nextcloud:

```bash
docker exec -u www-data nextcloud php occ user:sync-account-data
```

This step is especially useful after modifying LDAP attributes or group memberships, ensuring up-to-date data in the Nextcloud UI and permission system.

## Playwright / E2E: biber First-Login Caveat

When a Playwright scenario exercises the OIDC/LDAP path as `biber` (or any non-administrator persona) against a freshly provisioned Nextcloud stack, the very first login can fail or stall because the Nextcloud internal account has not yet been materialized from LDAP; this matches the situation described above. On subsequent logins the account exists and the flow behaves normally.

If a brand-new deployment must pass the `biber` end-to-end scenario on its first run, either:

- Pre-provision `biber` via `php occ ldap:check-user --update biber` (and any other personas used by the test suite) as part of the role's post-deploy tasks, or
- Extend `roles/web-app-nextcloud/files/javascript.js` (exposed to the login page through the injected `javascript.js.j2` template) with a small guard that detects the "user does not exist" Nextcloud error message and retries the OIDC handshake once after a short delay, giving the LDAP plugin time to provision the account.

Either approach keeps the Playwright suite deterministic without disabling the LDAP first-login-provisioning behavior that real users rely on.
