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
- **Delegated Grants:** The application realm enables fine-grained admin permissions (v2) and records admin events, which it deletes after `services.keycloak.events.admin.expiration_days`, a whole number of days above 0 (the role ships 365). Upgrade note: the first deploy to an existing realm sets this expiration, and Keycloak's scheduled cleanup then permanently deletes every admin event older than 365 days; export them before that deploy if you need them. With [web-svc-access-request](../web-svc-access-request/README.md) deployed, [15_admin_permissions.yml](tasks/update/15_admin_permissions.yml) lets the platform administrators grant every role group and each application's administrators grant the non-administrator roles of their application.

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
- While the realm federates LDAP, `KEYCLOAK_EMAIL_UPDATE_ENABLED` keeps `UPDATE_EMAIL` off and the address admin-only, because Keycloak 26.8.2 answers `UPDATE_EMAIL` for an LDAP user with HTTP 500: the `full name` mapper and the `first name` and `last name` mappers both declare `firstName` and `lastName` profile metadata, which `DefaultAttributes.getUserStorageProviderMetadata` cannot merge.

### Verified addresses only

Under `external`, the `email` claim carries Keycloak's `email` field, so the realm keeps unproven addresses out of tokens:

- With SMTP (`lookup('email', 'web-app-keycloak').enabled`), the realm sets `verifyEmail: true`, also on an existing realm at every deploy. A user whose address is not verified gets `VERIFY_EMAIL` at the next browser sign-in and receives a token only after following the link. A user without any address is not held. A password (direct) grant of such a user fails with `Account is not fully set up` until the address is verified; a client credentials grant of a service account evaluates no required action and is not affected.
- Without SMTP, `verifyEmail` stays off, because no link could be sent and every unverified user would be locked out. The `email_verified` claim then tells the apps the truth, and the address can only be changed by an administrator.
- The LDAP federation sets `trustEmail: true`: a user the federation imports for the first time is marked verified, because the directory is the platform's own and seeded from the inventory. An entry an LDAP tool (LAM, phpLDAPadmin) creates with an address is trusted the same way. Keycloak applies it only at the first import, so every deploy with LDAP and `verifyEmail` extends the same trust to the users imported earlier: before the settings converge turns `verifyEmail` on, [`files/python/email_verified.py`](files/python/email_verified.py) with `FEDERATION` marks every user linked to the realm's LDAP provider with a non-blank address verified (`tasks/update/06_users/email/federated.yml`). Local users without that link stay as they are, because their unverified state is what `verifyEmail` exists to catch. Inventory users are also marked verified at every deploy while `services.keycloak.users.emails_verified` is on (the default); any other local user confirms its address once through the link.
- If the mail provider is deployed but cannot deliver, a local user with an unverified address cannot finish `VERIFY_EMAIL` and stays locked out, and its password grants fail, until mail works or an administrator marks the address verified.
- Under `mailbox`, the claim carries the platform-owned mailbox with `email_verified` hardcoded to `true`, and the realm keeps `verifyEmail: false`.
- System alerts, Alertmanager and the certbot account mail go to the platform administrator's secondary address when it has one, and to its primary address otherwise.

### Leaving the mailbox policy

No deploy moves a realm from `mailbox` back to `external`. An operator who has to do it works through these steps by hand, with `kcadm.sh` inside the Keycloak container after `kcadm.sh config credentials` against the master realm:

1. In the directory, replace `mail` of every user entry with its `infinitoSecondaryMail`, through LAM, phpLDAPadmin or `ldapmodify`. An entry without a secondary address keeps its mailbox address until an administrator gives it another one.
2. Record the policy in the realm: `kcadm.sh update realms/<realm> -s attributes.infinitoEmailPolicy=external`.
3. Delete the read-only `mailbox` LDAP mapper, which no deploy removes: find the id of the component named `mailbox` in `kcadm.sh get components -r <realm> --fields id,name,parentId`, then run `kcadm.sh delete components/<id> -r <realm>`.
4. Set `services.keycloak.email.policy` to `external` in the inventory, drop `switch`, and deploy. The deploy points the `email` mapper back at `mail`, renders the user profile and the claims without the mailbox attribute, and removes the RBAC sync timer's mailbox seed.
5. Read every user again through the new mappers: `kcadm.sh create user-storage/<ldap-component-id>/sync?action=triggerFullSync -r <realm>`.

## Two-Factor Authentication

`services.keycloak.realm` in [services.yml](meta/services.yml) sets the access token lifetime of the application realm and decides how it offers one-time passwords. A fresh realm imports these values and every deploy converges an existing realm to them.

| Key | Default | Effect |
|---|---|---|
| `access_token_lifespan_seconds` | `300` | Lifetime of an access token the realm issues, a whole number of seconds above 0. Other roles read it through `lookup('config', 'web-app-keycloak', 'services.keycloak.realm.access_token_lifespan_seconds')` instead of keeping a copy, for example a store that must keep an erasure record until every token issued before it has expired. |
| `totp_enabled` | `true` | Enables the `CONFIGURE_TOTP` required action: a user can enroll an authenticator app in the account console. The browser flow asks every user who holds an OTP credential for a code, whatever this key says. |
| `totp_enforced` | `true` | Makes `CONFIGURE_TOTP` a default action, which Keycloak attaches to every user it creates while the key is `true`; see [Enforcing TOTP](#enforcing-totp). Needs `totp_enabled: true`, otherwise the deploy fails. |
| `otp_policy.type` | `totp` | `totp` (time-based) or `hotp` (counter-based). |
| `otp_policy.algorithm` | `HmacSHA1` | `HmacSHA1`, `HmacSHA256` or `HmacSHA512`. |
| `otp_policy.digits` | `6` | Code length, `6` or `8`. |
| `otp_policy.period` | `30` | Seconds a `totp` code stays valid. |
| `otp_policy.look_ahead_window` | `1` | Codes before and after the current one that Keycloak still accepts, for clock skew or skipped counters. |
| `otp_policy.initial_counter` | `0` | Starting counter of a `hotp` credential. |
| `otp_policy.code_reusable` | `false` | Whether a code may sign in more than once within its period. |

With the defaults the enrollment page lists FreeOTP, Google Authenticator and Microsoft Authenticator. Type `hotp` drops Microsoft Authenticator, and another algorithm, digit count or period leaves FreeOTP as the only app it lists. A credential keeps the type, algorithm, digits and period it was enrolled with, so a changed value of these reaches only credentials enrolled after the deploy. The look-ahead window and code reuse apply to every credential at once.

### Enforcing TOTP

TOTP is enforced by default. Only an inventory override switches it off:

```yaml
applications:
  web-app-keycloak:
    services:
      keycloak:
        realm:
          totp_enforced: false
```

- Keycloak attaches its default actions when it creates a user: on `kcadm.sh create users`, through which the deploy provisions the inventory users, among them the administrator and biber personas, while LDAP is off, and on the first import of a directory user from LDAP. Each such user enrolls an authenticator app before its first sign-in completes.
- A user Keycloak holds already keeps its required actions, so an existing user who never enrolled keeps signing in with the password alone until it enrolls in the account console.
- Switching back to `false` stops tagging new users, but every user tagged meanwhile keeps `CONFIGURE_TOTP` until an administrator removes it under Users, the user, Required user actions.
- The deploy converges the required actions before it creates or imports any user, so a changed key reaches the users of the same deploy.
- Development and CI switch it off, because the Playwright SSO personas and every other automated login would stop at the enrollment page. The development inventory vars file (`INFINITO_INVENTORY_VARS_FILE`) sets `totp_enforced: false` for every inventory `infinito administration inventory provision` builds from it, including `make compose-deploy` without `apps=` and `make compose-inventory-refresh`. Every variant in [variants.yml](meta/variants.yml) sets it as well, and the CI inventory build bakes the variant of every deployed app, providers included. A production inventory keeps the enforced default.

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

## Managed Client Fields

Every run writes the valid redirect URIs, the valid post logout redirect URIs and the web origins of the deployment's client, which `meta/forms.yml` declares as the enforced fields of the `client` form. In the admin console the shared lock renderer of [sys-front-inj-javascript](../sys-front-inj-javascript/README.md) renders them read-only while the page edits that client: each control shows the inventory path of its value as its hover title, one banner lists the fields, and a double-click with a confirmation unlocks a field until the page turns to another client. Every other client, the built-in ones and those an admin creates, stays editable. The inline loader fetches the renderer from `/infinito/field-lock.<sha1>.js` only on pages under `/admin/`, so the login and account pages carry none of it.

## Directory Client

`services.keycloak.directory_client.enabled` in [services.yml](meta/services.yml) ships `false`. Switched on, it adds the confidential client `<realm>-directory` to the application realm; `KEYCLOAK_DIRECTORY_CLIENT_ID` in [vars/main.yml](vars/main.yml) is its only definition. A deploy on an existing realm creates the client, and a deploy with the switch off deletes it together with its service account.

```yaml
applications:
  web-app-keycloak:
    services:
      keycloak:
        directory_client:
          enabled: true
```

The store gets its token by the client-credentials grant at `/realms/<realm>/protocol/openid-connect/token`. The secret is the credential `secrets.credentials.directory_client_secret` from [secrets.yml](meta/secrets.yml), which the workspace inventory holds. It reaches Keycloak only through the realm import file or the `kcadm` stdin payload, never on a command line.

The service account `service-account-<realm>-directory` holds exactly the `realm-management` roles `view-users`, `query-users` and `manage-users`, and every deploy revokes any other `realm-management` role it finds there. These three cover listing and searching users by `username` or `email`, creating and deleting them, and mapping non-admin realm roles to them. `view-realm` stays out, because it would expose the whole realm configuration to the token, so `GET /admin/realms/<realm>/roles/<name>` answers `403`. The store resolves role ids through `GET /admin/realms/<realm>/users/<id>/role-mappings/realm/available` instead, which lists exactly the realm roles the token may map. While `admin.allowed_networks` is set, the store's source network needs an entry, because these calls go to the admin REST API.

## OAuth2 Proxy Gate

A consumer role with `services.sso.flavor: oauth2` sits behind an oauth2-proxy rendered from [`templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2`](./templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2). Two keys under the consumer's `services.sso.oauth2` decide who passes:

- `allowed_groups` admits only members of the listed RBAC groups. The proxy requests the groups claim and forwards it as `X-Forwarded-Groups`.
- `allow_all_users: true` admits every authenticated realm user and still requests and forwards the groups claim, so the application derives roles from `X-Forwarded-Groups` itself.
- With neither, the proxy admits only accounts whose e-mail address belongs to `DOMAIN_PRIMARY` and requests no groups claim.

`allow_all_users: true` together with a non-empty `allowed_groups` fails the deploy. A list in the inventory replaces the list the role ships, so an inventory that opens the gate clears the groups as well:

```yaml
applications:
  web-app-example:
    services:
      sso:
        oauth2:
          allowed_groups: []
          allow_all_users: true
```

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to ([requirement 017](../../docs/requirements/017-playwright-biber-rbac-coverage.md)). A follow-up tightens them.

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

So the role keeps the credential its predecessor used. Before [svc-stack](../svc-stack/README.md) re-renders the environment file, `tasks/utils/capture_previous_admin.yml` reads `KEYCLOAK_PERMANENT_ADMIN_PASSWORD` out of the file still on disk. When the login after the restart is refused, `tasks/utils/converge/previous_admin.yml` signs in with that captured value and sets the permanent admin's password to the newly rendered one, which the restarted container already carries in its environment. The bootstrap fallback then stays what its name says: the path for an instance that has never been deployed.

A host with no previous environment file captures nothing and goes straight to the bootstrap path, which is the first deploy.

The temporary account is the user `keycloak_bootstrap` in [users.yml](meta/users.yml), username `keycloakbootstrap`, with no accounts. It exists only in the master realm, where Keycloak creates it from `KC_BOOTSTRAP_ADMIN_USERNAME` and `KC_BOOTSTRAP_ADMIN_PASSWORD`. The deploy creates no directory entry, realm user or mailbox for it, and the realm's user profile reserves its username.
