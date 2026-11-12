# Todos

- Implement working logout for all applications
- Implement general logout button
- Mode flip of the logout status panel: `sys-svc-webserver-core/tasks/03_directories.yml` applies the directory mode `0755` recursively to `conf.d/lua/web-app-keycloak-logout-panel.js`, and `📄 Deploy the logout status panel` in `tasks/00_core.yml` sets it back to `0644`, so that task reports `changed` and reloads the proxy on every second deploy. Options: give the task the mode the directory task enforces, or stop the directory task from recursing into files.
- The bootstrap fallback (`tasks/utils/login_bootstrap_admin.yml`) signs in as the user `meta/users.yml` names, but Keycloak creates that master user only on an empty database, so a master realm keeps the name of its first install: `administrator` before 3c72c2002a (2026-10-08), `keycloakbootstrap` from then on. On an older realm the fallback finds no user, so a refused permanent-admin login without a captured previous password stops the deploy, and the old temporary admin stays with its old password. Options: recover through Keycloak's own `kc.sh bootstrap-admin user` with credentials passed by environment instead of a stored master user, and delete every temporary admin once the permanent admin signs in.

## Email policy

- Self-registration is not a setting yet: `KEYCLOAK_REGISTRATION_ALLOWED` in `vars/main.yml` is `false`, and `services.keycloak.email.secondary_required` makes the secondary address required only once registration is allowed. When registration becomes a setting, add it to the realm settings reconcile in `KEYCLOAK_SETTINGS_SPEC` and decide whether users without a secondary address get the profile form at their next login, since Keycloak's `required` applies to every login, not only to registration.
- Under the `mailbox` policy an inventory user without an external address has no secondary address, so Keycloak can send it no mail; a password reset then goes through an administrator. The deploy invents no address.
- Every deploy converges `verifyEmail` onto an existing realm, and the federation sets `trustEmail: true`, which Keycloak 26.8.2 applies only when it first imports a user (`LDAPStorageProvider.doImportUser`); the deploy stamps the users imported earlier before the converge. A local realm user that a deploy creates after the converge (`06_users/realm.yml`) is unverified until the inventory stamp at the end of the same deploy, so a login in that window gets the link. An address that changes in LDAP outside Keycloak keeps the user's `emailVerified` flag, because the LDAP sync writes `email` without touching it. A user of an `external` realm with SMTP who holds no address yet can still set one in `UPDATE_PROFILE` or `VERIFY_PROFILE`: Keycloak 26.8.1 lets that profile form write a blank `email`, and the user profile config cannot make it admin-only for that case, because its `edit` permission knows only the roles `admin` and `user`. Keycloak then adds `UPDATE_EMAIL`, so the login only finishes once the user follows the confirmation link. Until then the address already sits in Keycloak and, through the writable federation, in LDAP `mail`. A Keycloak event listener or a profile validator that refuses a first address outside `UPDATE_EMAIL` would close that gap.
- A user created at runtime under the `mailbox` policy gets its LDAP `mail` from the `sys-ctl-mtn-rbac-sync` timer, up to 15 minutes after its creation (`SYS_SCHEDULE_MAINTANANCE_RBAC_SYNC`); until then the `email` claim is absent. A Keycloak event listener that sets the mailbox on registration would close that window.
- A mailbox realm cannot return to `external`; `kc_email_policy_change` refuses it. Build the reverse switch only when an operator needs it.
- The Playwright criterion "a change of the changeable address stays pending until the confirmation link is followed" has a spec in `files/playwright/test-email-policy.js` that has not run against a live stack yet. Its link half assumes the mail provider delivers a `+` sub-address of biber's address into biber's mailbox and that the Keycloak action token names the new address as `newEmail`; under `mailbox` the secondary address lies outside the mail domain, so only the pending half runs. Keycloak re-adds `UPDATE_EMAIL` at every login while a pending address exists, which would stop every later biber login of every suite, so the cleanup drops each user attribute whose name contains `pending` and the `UPDATE_EMAIL` required action through the admin API, and a fresh biber sign-in then proves that nothing is left pending.

## Req 019 rollout: deploy gate

- During the autonomous req 019 rollout, `make compose-deploy mode=reinstall apps=web-app-keycloak full_cycle=true` failed with two unrelated assertions:
  - `kcadm.sh config credentials` failed during the keycloak admin login phase (likely transient or env-scoped).
  - `run_once_web_app_mailu is defined` assertion failed in `sys-svc-mail`, indicating the service-loader did not preload Mailu in the keycloak-only deploy path.
- These are deployment-orchestration failures, not playwright-parity failures, and were therefore deferred per the autonomy escape clause (archived req 019).
- The role's playwright lint contracts (Tests A + B + env_keys_used) are green; role-closure remains pending the orchestration fix.

## Trusted-header SSO bridge migration

Roles still to migrate to the trusted-header SSO bridge (pattern: `web-app-baserow` / `web-app-bookwyrm`):

- `web-app-kix` — native OTRS header-auth module
- `web-app-friendica` — addon/hook: header → session
- `web-app-akaunting` — Laravel controller shim (stage shim into the named volume on every deploy)
- `web-app-magento` — custom `Infinito_HeaderSso` module (bypass FPC/Varnish on the handoff route)
- `web-app-funkwhale` — django header / remote-user auth backend
- Excluded: `web-app-flowise` (session-minting code is commercial-licensed), `web-app-jitsi` (no HTTP session — use native `AUTH_TYPE=jwt`), `web-app-suitecrm` (upstream SAML — use native `AUTH_TYPE=saml`)
