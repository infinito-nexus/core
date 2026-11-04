# 064 - Login Methods per Application

## User Story

As a platform operator, I want the sign-in page of every application to offer only the login methods its deployment mode allows, each switchable on its own in `meta/services.yml`, so that users see one way to sign in (the SSO button whenever Keycloak runs) and no side door bypasses the central identity.

## Decisions (operator-confirmed 2026-10-30; do not re-litigate)

1. **Schema.** Every role whose sign-in offers more than one method in any mode declares `services.<entity>.login.method.<method>.enabled` under its own entity in `meta/services.yml`. The methods are `sso`, `ldap`, `native` and `2fa`, plus the extras an app actually has: `passkey`, `openid2` (Gitea), `odoo_com` (Odoo), `email` (Fider magic link) and `registration` (local self-registration).
2. **Defaults by mode.** `sso` means `web-app-keycloak` in `group_names`, `ldap` means `svc-db-openldap` in `group_names`.

   | Mode | sso | ldap | native | 2fa | extras and registration |
   |---|---|---|---|---|---|
   | SSO on | true | false | false | false (Keycloak carries the second factor) | false |
   | SSO off, LDAP on | false | true | false | true | false |
   | SSO off, LDAP off (native) | false | false | true | true | false |

   The inventory may override any flag.
3. **2FA is offered, never enforced.** `2fa: true` makes the app's own second factor available for enrollment; no account is forced to enroll.
4. **Shared form.** Where one form serves local and LDAP accounts (Gitea, Open WebUI, Matrix, MinIO, Semaphore, Zammad, Odoo), the LDAP mode keeps the form for LDAP, and `native: false` means no local account signs in except the break-glass admin wherever the app can tell the two apart; where it cannot, the role README states that the form is shared.
5. **Hiding.** A disabled method is switched off through the app's own setting where one exists, otherwise hidden by role-injected CSS or JavaScript through the role's `javascript` service. Every app keeps a documented break-glass path for its local admin (URL parameter, recovery account, CLI or token).
6. **Gitea OpenID 2.0.** `[openid] ENABLE_OPENID_SIGNIN` and `ENABLE_OPENID_SIGNUP` enable OpenID 2.0, not the OIDC source, and follow `login.method.openid2.enabled`.

## Acceptance Criteria

### Schema and lint

- [ ] Every role whose sign-in page offers more than one method in any mode declares `login.method.<method>.enabled` under its entity for every method the app offers, and declares no method the app lacks.
- [x] A lint fails when a role's default for any declared method deviates from the mode table, and it fails on a negative control.
- [x] A lint fails when a role in scope lacks the `login.method` block, and it fails on a negative control.
- [x] An inventory override of a single method flag reaches the rendered app configuration, proven by a unit test per switch kind (environment, config file, database setting, injected CSS or JavaScript).
- [x] The existing role-local switches (`discourse.local_login_enabled`, `nextcloud.legacy_login_mask`, `PENPOT_NATIVE_LOGIN_ENABLED`, `MEDIAWIKI_LOCAL_PASSWORD_LOGIN`, `OPENBAO_USERPASS_ENABLED`, `MOBILIZON_INSTANCE_DISABLE_DATABASE_LOGIN`, Taiga's `defaultLoginEnabled`, the Listmonk login script) derive from `login.method.*` and keep no second source.

### SSO mode

- [ ] With SSO on, the sign-in page of every role in scope shows only the SSO entry: no password form, passkey, OpenID 2.0, third-party, magic-link or registration entry, proven by a Playwright assertion in each role's spec.
- [ ] With SSO on, an LDAP account signs in through Keycloak's LDAP federation in every role whose LDAP spec ran with SSO on before (Penpot, Open WebUI, Semaphore, MinIO, Gitea, Discourse), and those native LDAP specs are gated to SSO off.
- [ ] Gitea shows no "Sign in with OpenID" entry in any mode, and Odoo shows no "Sign in with Odoo.com" entry and no passkey entry in any mode.

### LDAP and native modes

- [ ] With SSO off and LDAP on, every role with a native LDAP path signs an LDAP account in through its form, and shows no registration, passkey or third-party entry.
- [ ] With SSO off and LDAP on, a local account other than the break-glass admin cannot sign in wherever the app separates local from LDAP accounts, and the README of every other shared-form role says so.
- [ ] With SSO and LDAP off, every role signs a local account in through its form and offers its own second factor for enrollment where the app has one, without enforcing it.

### Break-glass

- [ ] Every role in scope documents its break-glass path in its README, and where that path is a browser or HTTP API path, a Playwright spec signs the local admin in through it with SSO on.
- [ ] Every Playwright spec that signed in through the local form while SSO was on uses the break-glass path instead (GitLab root, Gitea design, Matomo superuser, pgAdmin, Decidim, ERPNext, Jellyfin, PeerTube root, the Mattermost SSO flow).

### Quality

- [ ] `make test` passes, including the new lints and unit tests.
- [ ] Every role in scope deploys green in compose and in swarm with SSO on, and in its LDAP-only and native variants where it has them.
- [x] Every role README in scope lists its login methods, the switch behind each one and its break-glass path.
