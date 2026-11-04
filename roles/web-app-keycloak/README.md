# Keycloak

## Description

Step into a secure future with [Keycloak](https://www.keycloak.org/)! This open‐source identity and access management solution offers powerful single sign-on (SSO), multi-factor authentication, and user federation capabilities. With support for industry standards such as SAML and OpenID Connect, Keycloak helps you protect and streamline access to your applications.

## Overview

This role deploys Keycloak in a Docker environment, integrating it with a PostgreSQL database and enabling operation behind a reverse proxy such as NGINX. It manages container orchestration and configuration via Docker Compose and environment variable templates, ensuring a secure and scalable identity management solution.

## Features

- **Comprehensive Identity Management:** Manage users, roles, and permissions across your applications with robust SSO and user federation.
- **Advanced Security Options:** Benefit from multi-factor authentication, configurable password policies, and secure session management.
- **Standards Support:** Seamlessly integrate with SAML, OpenID Connect, and OAuth2 to support various authentication flows.
- **Scalable and Customizable:** Easily tailor settings and scale your Keycloak instance to meet growing demands.
- **Directory Profile:** Contact, address, locale and organization attributes from OpenLDAP appear in the account and admin consoles under "Contact and locale" (user-editable) and "Organization" (administrator-only), and reach applications through the standard `profile`, `phone` and `address` claims.
- **Admin Console Roles:** The groups `user-manager`, `auditor` and `impersonator` under `/roles/web-app-keycloak` grant user management, read-only auditing and impersonation in the application realm. Each role lists its `realm-management` client roles under `realm_management` in [rbac.yml](meta/rbac.yml). `realm-admin` stays with the local bootstrap account. A user manager can change group memberships, which includes every application role group, so grant `user-manager` only to people trusted with every application role.
- **Delegated Grants:** The application realm enables fine-grained admin permissions (v2) and records admin events. With [web-svc-access-request](../web-svc-access-request/README.md) deployed, [15_admin_permissions.yml](tasks/update/15_admin_permissions.yml) lets the platform administrators grant every role group and each application's administrators grant the non-administrator roles of their application.

## Developer Notes

For the OIDC variable tree, claim rules, and the policy that app-specific protocol mappers belong in per-client scope files (not in the shared `clients/default.json.j2`), see [oidc.md](../../docs/contributing/design/iam/oidc.md).

## Email Policy

`services.keycloak.email.policy` in [services.yml](meta/services.yml) decides which address a user's primary one is.

| Policy | Primary address (`email` claim, SAML, LDAP `mail`) | Keycloak `email` field |
|---|---|---|
| `external` (default) | the address the user brings | the primary address |
| `mailbox` | `<username>@<DOMAIN_PRIMARY>`, read-only attribute `mailbox` | the secondary address, LDAP `infinitoSecondaryMail` |

- `mailbox` needs `svc-db-openldap`, which stores both addresses; a deploy with `mailbox` and `services.ldap.enabled: false` fails.
- A new inventory, one without `devices.yml` and without host_vars, that deploys Keycloak, the mail provider and `svc-db-openldap` records `mailbox`. `make compose-inventory-refresh` carries the policy and `switch` of the inventory it replaces over. An existing inventory keeps `external` until the operator sets `policy: mailbox` together with `switch: true`; the switch keeps every existing address as secondary address. A mailbox realm cannot return to `external`.
- The realm records the policy it holds in its attribute `infinitoEmailPolicy`. A deploy whose policy differs from it without `switch: true` fails.
- The inventory address only seeds a user: a deploy writes it into LDAP `mail` or the realm user once and never overwrites an address the user changed and confirmed. Change an existing user's address in the Keycloak console.
- Under `mailbox`, a user created at runtime (admin console, admin API, registration) gets its LDAP `mail` from the [RBAC sync timer](../sys-ctl-mtn-rbac-sync/README.md), which runs every 15 minutes (`SYS_SCHEDULE_MAINTANANCE_RBAC_SYNC`). Until its next run the user has no `mailbox` attribute and no `email` claim. The timer sets `mail` only on entries that hold none.
- With SMTP, a user changes the changeable address through `UPDATE_EMAIL` with forced verification: the new address takes effect after the user follows the link sent to it. Without SMTP only an administrator can change it.
- System alerts, Alertmanager and the certbot account mail go to the platform administrator's secondary address when it has one, and to its primary address otherwise.

### Leaving the mailbox policy

No deploy moves a realm from `mailbox` back to `external`. An operator who has to do it works through these steps by hand, with `kcadm.sh` inside the Keycloak container after `kcadm.sh config credentials` against the master realm:

1. In the directory, replace `mail` of every user entry with its `infinitoSecondaryMail`, through LAM, phpLDAPadmin or `ldapmodify`. An entry without a secondary address keeps its mailbox address until an administrator gives it another one.
2. Record the policy in the realm: `kcadm.sh update realms/<realm> -s attributes.infinitoEmailPolicy=external`.
3. Delete the read-only `mailbox` LDAP mapper, which no deploy removes: find the id of the component named `mailbox` in `kcadm.sh get components -r <realm> --fields id,name,parentId`, then run `kcadm.sh delete components/<id> -r <realm>`.
4. Set `services.keycloak.email.policy` to `external` in the inventory, drop `switch`, and deploy. The deploy points the `email` mapper back at `mail`, renders the user profile and the claims without the mailbox attribute, and removes the RBAC sync timer's mailbox seed.
5. Read every user again through the new mappers: `kcadm.sh create user-storage/<ldap-component-id>/sync?action=triggerFullSync -r <realm>`.

## Admin Console Access

`services.keycloak.admin.allowed_networks` limits every path under `/admin`, which carries the admin console and the admin REST API under `/admin/realms`, to the listed source networks. Each entry is an IPv4 or IPv6 address or a CIDR block. The vhost renders one `allow` per entry followed by `deny all`, so any other client gets `403`. The list ships empty, and an empty list leaves `/admin` open. Declare it in the inventory:

```yaml
applications:
  web-app-keycloak:
    services:
      keycloak:
        admin:
          allowed_networks:
            - 203.0.113.0/24
            - 2001:db8::/48
```

The OIDC endpoints under `/realms/` and the static assets under `/resources/` stay public.

The deploy's `kcadm.sh` logins need no entry: every one, including the ones `web-app-opentalk` and `web-app-mattermost` make, runs inside the Keycloak container against `KEYCLOAK_SERVER_INTERNAL_URL`. While the list is set, `/` redirects to the account console of the platform realm instead of to `/admin/`, so the CSP health check and the proxy probe, which request `/` from the host itself, need no entry either. Clients that call `/admin` through the public URL need their source network in the list:

- The OpenTalk controller's user search calls the admin REST API from its container, so the vhost sees the container's Docker network address. `NETWORK_INTERNAL_CIDRS` covers the loopback and private ranges those addresses come from.
- Onion visitors reach the vhost from the Tor daemon's address.
- The Playwright suites of several roles read and change realm groups through the admin REST API.

## Further Resources

- [Keycloak Official Website](https://www.keycloak.org/)
- [Official Keycloak Documentation](https://www.keycloak.org/documentation.html)
- [Keycloak GitHub Repository](https://github.com/keycloak/keycloak)
- [Setting up Keycloak behind a Reverse Proxy](https://www.keycloak.org/server/reverseproxy)
- [Wikipedia](https://en.wikipedia.org/wiki/Keycloak)
- [Youtube Tutorial](https://www.youtube.com/watch?v=fvxQ8bW0vO8)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/RMmxgQ2NKW3dmY3U36UmGd)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2`. Keycloak provides SSO rather than consuming it: `meta/services.yml` carries no `sso` block (the `keycloak` service declares `provides: sso`) and pins `logout.enabled: false`, so the canonical URL has neither an oauth2-proxy gate nor an in-app OIDC login link for the shared persona helpers to click or log out of. The administrator persona is additionally out of reach because Keycloak's only admin surface is the master-realm console, which accepts the permanent super-admin account (`KEYCLOAK_PERMANENT_ADMIN_USERNAME` / `KEYCLOAK_PERMANENT_ADMIN_PASSWORD` in `vars/main.yml`) under its own login name and not the normal-realm one the helper types.

Both journeys are covered bespoke in `files/playwright/playwright.spec.js`: the master-realm super administrator drives the admin console, and the normal-realm administrator and biber each drive the realm account console including sign-out. The path back to the generic personas is an app-shaped surface behind the shared auth chain, which the identity provider by definition does not have.

## Absorbing a password rotation

Keycloak stores the permanent admin's password in its database, so a rotated inventory value authenticates against nothing and the role would be locked out of its own instance. The temporary account from `KC_BOOTSTRAP_ADMIN_*` is no way back either: Keycloak writes it once, on an empty database, and upstream states it is meant to be deleted once a permanent admin exists.

So the role keeps the credential its predecessor used. Before `sys-stk-full` re-renders the environment file, `tasks/utils/capture_previous_admin.yml` reads `KEYCLOAK_PERMANENT_ADMIN_PASSWORD` out of the file still on disk. When the login after the restart is refused, `tasks/utils/converge/previous_admin.yml` signs in with that captured value and sets the permanent admin's password to the newly rendered one, which the restarted container already carries in its environment. The bootstrap fallback then stays what its name says: the path for an instance that has never been deployed.

A host with no previous environment file captures nothing and goes straight to the bootstrap path, which is the first deploy.

The temporary account is the user `keycloak_bootstrap` in [users.yml](meta/users.yml), username `keycloakbootstrap`, with no accounts. It exists only in the master realm, where Keycloak creates it from `KC_BOOTSTRAP_ADMIN_USERNAME` and `KC_BOOTSTRAP_ADMIN_PASSWORD`. The deploy creates no directory entry, realm user or mailbox for it, and the realm's user profile reserves its username.
