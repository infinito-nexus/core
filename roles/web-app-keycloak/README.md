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

Keycloak 26.8.2 answers `401` to an admin REST API call whose token lacks the built-in client scope `kc-admin-api`, so the clients whose service accounts call that API, `usage`, `workspace-members`, `export` and `opentalk-controller`, carry it as a default client scope, and [admin_api_scope.yml](tasks/utils/admin_api_scope.yml) stops a deploy whose realm lacks it instead of creating a look-alike. A user's token reaches that API only through an oauth2-proxy gate client that lists the scope under `services.sso.oauth2.client.scopes` (see [OAuth2 Proxy Gate](#oauth2-proxy-gate)); the shared client never carries it.

## Managed Client Fields

Every run writes the valid redirect URIs, the valid post logout redirect URIs and the web origins of the deployment's client, which `meta/forms.yml` declares as the enforced fields of the `client` form. In the admin console the shared lock renderer of [sys-front-inj-javascript](../sys-front-inj-javascript/README.md) renders them read-only while the page edits that client: each control shows the inventory path of its value as its hover title, one banner lists the fields, and a double-click with a confirmation unlocks a field until the page turns to another client. Every other client, the built-in ones and those an admin creates, stays editable. The inline loader fetches the renderer from `/infinito/field-lock.<sha1>.js` only on pages under `/admin/`, so the login and account pages carry none of it.

## Usage Client

`services.keycloak.usage_client.enabled` in [services.yml](meta/services.yml) ships `false`; variant 0 turns it on. Switched on, it adds the confidential client `usage` to the application realm; `KEYCLOAK_USAGE_CLIENT_ID` in [vars/main.yml](vars/main.yml) is its only definition. A deploy on an existing realm creates the client and converges its service account ([18_usage_client](tasks/update/18_usage_client/enabled.yml)); a deploy with the switch off deletes it together with its service account.

```yaml
applications:
  web-app-keycloak:
    services:
      keycloak:
        usage_client:
          enabled: true
```

The service account `service-account-usage` holds exactly `view-users` of `realm-management`, and every deploy revokes any other `realm-management` role it finds there, so its token reads users and changes nothing. The secret is `secrets.credentials.usage_client_secret` from [secrets.yml](meta/secrets.yml); a workspace keeps it as an OpenBao reference that only a task of its `usage` template reads. It reaches Keycloak only through the realm import file or the `kcadm` stdin payload, never on a command line.

### Usage Count

The Semaphore template `usage` ([web-app-semaphore](../web-app-semaphore/README.md)) runs [playbook-usage.yml](../../playbook-usage.yml) on the workspace runner over the `web-app-keycloak` hosts of the workspace inventory, limited to the hosts of `WORKSPACE_TARGETS` and with `ansible_connection` `local`. The playbook includes only [tasks/usage.yml](tasks/usage.yml), which the role's `main.yml` never runs. The tasks hand the switch, the realm, the origin from the TLS lookup and, only while the switch is on, `secrets.credentials.usage_client_secret` to [files/python/usage.py](files/python/usage.py) on stdin, never in an argument or the environment, and the task is masked by `MASK_CREDENTIALS_IN_LOGS`.

With the switch off the script makes no call and reports `active_users` null. Otherwise it takes a client-credentials token of `usage` over verified HTTPS and reads every page of `GET users`. It counts the enabled users, without service-account users and without the master realm's technical administrator.

## Workspace Organizations

`services.keycloak.organizations.enabled` in [services.yml](meta/services.yml) ships `false`; variant 0 and every inventory that runs the store turn it on. Switched on, the realm has `organizationsEnabled` true and the `organization` execution of `Browser - Conditional Organization` `DISABLED`, so the login page stays one step. A deploy on an existing realm converges both, the clients below and the roles of their service account ([17_organizations.yml](tasks/update/17_organizations.yml)).

A workspace is one organization named `ws-<id>`, where `<id>` is the store's lowercase UUID. The attribute `workspace.id` holds `<id>`; it is the workspace marker, and every template finds the organization only by it. No marker or two markers make every writing template refuse; an organization a Keycloak admin created by hand with the alias `ws-<id>` makes `apply` fail with 409. The organization holds five groups, and a member sits in exactly one:

| Group | Semaphore role in the workspace project |
| --- | --- |
| `Owner` | `task_runner` |
| `Admin` | `task_runner` |
| `Operator` | `task_runner` |
| `Billing` | none |
| `Viewer` | `guest` |

The client `workspaces` enables no flow and holds the client roles `<id>:<role>`, each mapped onto its group. The client scope `workspace_roles` writes them through the stock "User Client Role" mapper as the flat claim `workspace_roles`, and the stock `organization` claim lists the alias of every membership. The store computes a user's rights from these two claims of the user's own token, with no admin read.

Every consumer that needs it declares its own confidential client under `services.sso.oidc.clients` and renders it through the macro `consumer_client` of [consumer.json.j2](templates/import/clients/consumer.json.j2): standard flow only, its own redirect URIs and web origins, its secret from its own credentials. The store's client is a login client only: no service account, no realm-management role, `rootUrl` and `baseUrl` on the store's origin so an invitee returns to it, `workspace_roles` as a default scope, and one `oidc-audience-mapper` that puts its own client id into `aud`. The store mounts its secret as a file with mode `0600` and passes only the path as `KEYCLOAK_CLIENT_SECRET_FILE`.

Core ships no store, so the realm holds a test-only client of the same shape, `workspace-store-fixture` from [store_fixture.json.j2](templates/import/clients/store_fixture.json.j2) on the origin of `web-app-semaphore`, while organizations are on and `services.semaphore.workspaces.invite_client_id` of `web-app-semaphore` names it. Only variant 0 of [web-app-semaphore](../web-app-semaphore/meta/variants.yml) does, so the store specs of [test-organizations.js](files/playwright/test-organizations.js) run in its rounds and no deployment outside them gets the client.

The store holds no Keycloak admin role. Core's confidential client `workspace-members` enables no flow, and its service account holds exactly `manage-organizations` and `manage-users` of `realm-management`; its secret is `secrets.credentials.workspace_members_client_secret` from [secrets.yml](meta/secrets.yml). Reading a realm role by name, `GET /admin/realms/<realm>/roles/<name>`, needs `view-realm` of `realm-management` on Keycloak 26.8.2 with and without fine-grained admin permissions v2; no client the store reaches holds it, so none of them reads role configuration. The store starts these templates of the Workspaces project:

| Store operation | Template and action | Survey variables |
| --- | --- | --- |
| Create a workspace | `workspace` `apply` | `WORKSPACE`, `WORKSPACE_ACTION` |
| Make the creator the first `Owner` | `members` `add` | `WORKSPACE`, `MEMBERS_ACTION`, `WORKSPACE_SUSPENDED`, `WORKSPACE_MEMBER` |
| Invite by address | `members` `invite` | `WORKSPACE`, `MEMBERS_ACTION`, `WORKSPACE_SUSPENDED`, `INVITE_KEY` |
| Revoke a pending invitation | `members` `uninvite` | `WORKSPACE`, `MEMBERS_ACTION`, `WORKSPACE_SUSPENDED`, `INVITE_KEY` |
| Change a member's role, transfer `Owner` | `members` `role` | `WORKSPACE`, `MEMBERS_ACTION`, `WORKSPACE_SUSPENDED`, `WORKSPACE_MEMBER`, `WORKSPACE_ROLE` |
| Remove a member | `members` `remove` | `WORKSPACE`, `MEMBERS_ACTION`, `WORKSPACE_SUSPENDED`, `WORKSPACE_MEMBER` |
| Place accepted invitees, mirror Semaphore | `members` `sync` | `WORKSPACE`, `MEMBERS_ACTION`, `WORKSPACE_SUSPENDED` |
| List members and pending invitations | `members` `list` | `WORKSPACE`, `MEMBERS_ACTION`, `WORKSPACE_SUSPENDED` |
| Delete a workspace | `workspace` `destroy` | `WORKSPACE`, `WORKSPACE_ACTION` |
| Delete a platform account | `user` `erase` | `USER_ACTION`, `USER_ID` |

[members.py](files/python/workspace/members.py) does the Keycloak half of `members`:

- `add` makes an existing user the first member and puts them into `Owner`; a second member or a pending invitation refuses it.
- `invite` reads the staged invitation `{email, role}` at `platform/data/store/invites/<id>/<INVITE_KEY>` in OpenBao with the task's own token, so no address passes through the survey, the task input or the log. It sends a Keycloak invitation with the store's client id and records `workspace.pending.<role>`, which lists the key, and `workspace.invite.<key>`, which holds the address. A pending key sends no second mail, and a member's address is refused. The store erases the staged entry itself; core only reads it.
- `uninvite` deletes every invitation of the key's address and drops its two attributes.
- `role` keeps the member in exactly the given group; `remove` takes them out of every group and ends the membership. Both refuse to leave no enabled `Owner`; `remove` also refuses a `MANAGED` membership and a holder of a platform RBAC role.
- `sync`, which ends every action but `list`, places each accepted invitee into the invited group and drops the entries Keycloak holds no invitation for.
- `list` writes nothing; without a marked organization it prints `{"workspace":"<id>","absent":true}`.

Every change prints one `change workspace=<id> action=<action> ...` line with the user id and group, never a secret. The last line lists the members, each with id, groups and `enabled`, and the pending keys with their role, but no name, username or address. A refusal exits 3 with the last line `{"workspace":"<id>","refused":"<reason>"}`, `<reason>` one of `last_owner`, `not_first`, `member_address`, `not_member`, `managed`, `platform_role` and `absent`; any other failure exits 1 without that line, so the store runs it again.

`user erase` ([user.py](files/python/workspace/user.py)) deletes a platform account in Keycloak and, through the writable LDAP federation, in the directory. It refuses a member of a marked organization and a holder of a platform RBAC role (`{"user":"<id>","refused":"member"}`, `platform_role`), prints the user id and no address, and ends with `{"user":"<id>","erased":true}`.

`workspace destroy` ([organization.py](files/python/workspace/organization.py)) runs after every other resource of the workspace is gone, deletes the five client roles and then the organization with its groups, so the marker outlives everything else. Every action checks the state before each change, and an object already gone counts as done, so an action that failed at any step finishes when the store runs it again, and a further run changes nothing.

The export of a workspace's secrets as a KeePassXC database reads Keycloak through core's confidential client `export`. It enables no flow, and its service account holds exactly `view-users`, `view-organizations` and `view-events` of `realm-management`, so it reads users, organization groups and admin events and changes nothing; [17_organizations.yml](tasks/update/17_organizations.yml) converges it beside `workspace-members`. Its secret is `secrets.credentials.export_client_secret`. OpenBao deploys after Keycloak, so the Semaphore deploy hands `client_id` and `client_secret` to OpenBao at `platform/export/keycloak` through [export_login.yml](tasks/utils/export_login.yml), on stdin and without a log, whenever organizations are on and the inventory holds an OpenBao host. The user profile declares the single-valued attribute `export_recipient`, which only its user edits and admins only view, so neither `workspace-members` nor any template writes it. Its pattern admits exactly one age recipient, `age1` and 58 lowercase bech32 characters, as the export script checks. It has no LDAP mapper and reaches no claim or SAML assertion. The client, its service account and the attribute exist only with organizations on.

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

The gate signs in through the shared client `OIDC.CLIENT.ID` unless the consumer declares a client of its own:

```yaml
sso:
  flavor: oauth2
  oauth2:
    client:
      id: access-request
      scopes: [kc-admin-api]
```

`id` and `scopes` are both required; `scopes` lists the default client scopes the client carries beyond the shared login scopes. The realm then holds that client from [proxy.json.j2](templates/import/clients/proxy.json.j2): confidential, standard flow only, its redirect URIs the consumer's `/oauth2/callback` on every network, its secret `secrets.credentials.sso_proxy_client_secret` from the consumer's own `meta/secrets.yml`, and one `oidc-audience-mapper` that puts its own id into `aud`. The [alpha config](templates/sso_proxy/oauth2-proxy-keycloak-alpha.yml.j2) signs the gate in with that id and secret. `KEYCLOAK_PROXY_CLIENTS` in [vars/main.yml](vars/main.yml) lists the clients of the deployed consumers, so a deploy on an existing realm creates and converges them like the declared clients.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## LDAP group leave

Keycloak 26.8.2, pinned in [`meta/services.yml`](./meta/services.yml), removes a federated user from more than the group they leave. When a user leaves one app's role group, for example `/roles/web-app-joomla/administrator`, `GroupLDAPStorageMapper.leaveGroup` of every app's LDAP group mapper looks the group up by its name alone and also drops the user's `member` value from that app's own role group of the same name. One removal therefore takes `administrator` away in every app. It only ever revokes access, never grants it, and it hits every role removal made through Keycloak, in production too, including the leave of a Keycloak organization group whose name matches a role description.

The per-app mapper of a tenant-unaware app lists each of its role groups as an exact `cn=<app>-<role>`, built by `kc_app_ldap_scopes` in [build_realm_rbac_groups.py](./filter_plugins/build_realm_rbac_groups.py). A mapper therefore never reads the groups of an app whose id extends its own, such as `svc-net-tor` and `svc-net-tor-smtp`, and no leave fails with HTTP 400 (`multiple LDAP objects`) on such an overlap.

The cascade itself stays, because the leave uses the same search every mapper uses to read its own groups. The upstream fix (commit `b39c237efb`, issue 50984) ships with Keycloak 27.0.0, and the pin moves there once it is released. Until then every Playwright leave of a role group goes through `keycloakRemoveUserFromGroupViaRest` in [keycloak.js](../test-e2e-playwright/files/personas/utils/keycloak.js). It joins the user back into each group the leave dropped besides the one it targets, also after a failed leave, and names every leave or rejoin that failed. A spec that changes several groups at once leaves them all before it joins any. A leave that bypasses the helper strips the user from every app of the deployment, and the next role's suite meets a 403 from its oauth2-proxy. The workspace member sync in [members.py](./files/python/workspace/members.py) still leaves the sign-in group and the organization role groups (Owner, Admin, Operator, Viewer; `description` matches case-insensitively) without that rejoin.

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
