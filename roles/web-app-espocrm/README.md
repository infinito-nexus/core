# EspoCRM

## Description

Enhance your sales and service processes with EspoCRM, an open-source CRM featuring workflow automation, LDAP/OIDC single sign-on, and a sleek, lightweight UI! 🚀💼

## Overview

This Ansible role deploys EspoCRM using Docker. It handles:

- MariaDB database provisioning via the `sys-svc-rdbms` role  
- NGINX domain setup with WebSocket and reverse-proxy configuration  
- Environment variable management through Jinja2 templates  
- Docker Compose orchestration for **web**, **daemon**, and **websocket** services  
- Automatic OIDC scope configuration within the EspoCRM container  

With this role, you'll have a production-ready CRM environment that's secure, scalable, and real-time.

## Addons

Role-level extensions are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `oidc` | `extension` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `outbound-emails` | `extension` | enabled whenever the `email` service is present (`web-app-email` co-deployed) | `email` → `web-app-email` |

Both name surfaces EspoCRM ships itself, so their payload stays with [`templates/env.j2`](./templates/env.j2), which renders `ESPOCRM_CONFIG_OIDC_*` and `ESPOCRM_CONFIG_SMTP_*` from the same service flags the addons' `enabled` expressions read; [`files/php/seed/config.php`](./files/php/seed/config.php) writes them into EspoCRM's own config.

## Features

- **Workflow Automation:** Create and manage automated CRM processes with ease 🛠️  
- **LDAP/OIDC SSO:** Integrate with corporate identity providers for seamless login 🔐  
- **Login methods:** `services.espocrm.login.method` declares `sso`, `ldap`, `native` and `2fa` (see [Login Methods](../../docs/contributing/design/iam/login.md)). EspoCRM runs one `authenticationMethod` at a time, so `services.espocrm.authentication_method` maps them onto it: `Oidc` while `sso` is on, else `LDAP` while `ldap` is on, else `Espo` (the local form). The switches travel as `ESPOCRM_SEED_*` keys, which [`files/php/seed/config.php`](./files/php/seed/config.php) writes on every deploy, so an inventory override reaches a running install. Under `Oidc`, `native` drives `oidcFallback`, which is off by default so the sign-in page shows only the Keycloak button, and `oidcAllowRegularUserFallback` stays unset, so a fallback form admits administrators only. `2fa` drives `auth2FA` (TOTP from the default `auth2FAMethodList`) through the seeder key `ESPOCRM_SEED_AUTH2_F_A`, and `login.method.2fa.enforced` (default `true`) drives `auth2FAForced` through `ESPOCRM_SEED_AUTH2_F_A_FORCED`, so a regular user without a second factor enrolls one at the next sign-in; while `2fa` is off both are written `false`; EspoCRM cannot force portal users and bypasses the second factor for an OIDC sign-in.
- **Managed settings:** [`meta/forms.yml`](./meta/forms.yml) declares `authenticationMethod`, `auth2FA`, `auth2FAForced` and `oidcFallback` (Administration > Authentication) and `maintenanceMode`, `cronDisabled` and `useCache` (Administration > Settings); their values reach the seeder only through the form sinks. Each deploy first runs the seeder in read mode, reports every managed setting it is about to revert through the shared drift report, and writes only while something differs. The module `InfinitoForms` marks exactly these settings `readOnly` in EspoCRM's `Settings` metadata, so the admin UI shows them read-only and the settings API drops them from a save; `bin/command config:set` still reaches them for break-glass.
- **Break-glass access:** with SSO on, the local administrator has no form until an operator runs `bin/command config:set oidcFallback true --type=bool` in the EspoCRM container; the administrator then signs in with its local password at the form, which admits administrators only, and the next deploy resets `oidcFallback` to `login.method.native`. The administrator password itself is realigned with `command.php set-password` on every deploy.
- **Group-Based Teams and Roles:** [`files/php/seed/rbac.php`](./files/php/seed/rbac.php) keeps the teams `Users` and `Managers` with the roles `User` (team read, own edit, no delete) and `Manager` (every record), maps the `user` and `manager` role groups onto them through the groups claim (`oidcGroupClaim`, `oidcSyncTeams`, `oidcTeamsColumns`) and switches `aclStrictMode` on, so an account without a role group reaches no CRM record. It also sets the teams of existing accounts from the role-group members and makes the members of the `administrator` group EspoCRM administrators, every other account a regular user; the platform administrator, API and system users are never changed. It runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer. With LDAP only, `ldapUserLoginFilter` admits only the members of the role groups.
- **Role-Group Sign-In:** every deploy installs the module `InfinitoRbac` ([`group_user_provider.php`](./files/php/rbac/group_user_provider.php), [`binding.php`](./files/php/rbac/binding.php)) into `custom/Espo/Modules`, which replaces EspoCRM's OIDC user provider. A Keycloak sign-in without the `administrator`, `manager` or `user` group of this application is refused before EspoCRM creates an account, and an existing administrator account of such a user becomes a regular user. Each admitted sign-in sets the user type from the groups claim: `administrator` group members become EspoCRM administrators, every other member a regular user. The platform administrator signs in without a group and keeps its type. With LDAP only, the module's sign-in hook [`ldap_role_groups.php`](./files/php/rbac/ldap_role_groups.php) (`onSuccessHookClassNameList`) reads the account's `memberOf` from the directory at every password sign-in and applies the teams and user type `rbac.php` would set, so an account the LDAP login creates, or whose role groups changed, reaches its CRM records in that session instead of after the next RBAC run. When the directory cannot be read, the account keeps its teams and type until that run.
- **WebSocket Notifications:** Real-time updates via ZeroMQ and WebSockets 🌐  
- **Config via Templates:** Fully customizable `.env` and `compose.yml` with Jinja2 ⚙️  
- **Health Checks & Logging:** Monitor service health and logs with built-in checks and journald 📈  
- **Version Upgrades:** The first start of a new image migrates the data through EspoCRM's `migrate` command, and the deploy waits until the data reports the image version; data written by a newer EspoCRM than the image stops the start.
- **Currency List:** Before and after each install or migration, the entrypoint adds the default and base currency to `currencyList` when they are missing from it.
- **Network Siblings:** [`templates/config-override.php.j2`](./templates/config-override.php.j2) becomes `data/config-override.php`, which answers `siteUrl` with the onion sibling's base URL when a request arrives on that host, so the OIDC `redirect_uri` EspoCRM derives from `siteUrl` returns the login to the host it started on. `data/config.php` keeps the canonical URL, so the CLI and the clearnet host read it unchanged.
- **Modular Role Composition:** Leverages central roles for database and NGINX, ensuring consistency across deployments 🔄  

## AI Assistance

This role deploys no AI surface and declares no `litellm` service, because EspoCRM's open-source distribution does not ship one. At the pinned version `10.0.4`, `application/Espo/Modules` contains only `Crm`, `application/Espo/Resources/metadata/app/config.json` declares no AI key, and the release ZIP the image is built from leaves `custom/Espo/Modules` empty. The AI features (Summary, Intelligent Paste, AI Email Composer, AI formula functions) live exclusively in the commercial [Intelligence extension](https://www.espocrm.com/extensions/intelligence/), which is closed source, requires a purchased license, and is published in no `espocrm` GitHub repository. Bumping the version does not change this: the extension is documented as requiring EspoCRM 10.0.3 or greater, so newer cores stay hosts for it rather than absorbing it.

To connect EspoCRM to the platform gateway once a license is available:

1. Obtain the extension ZIP and make it reachable from the stack host at deploy time.
2. Install it inside the container with `bin/command extension --file="path/to/package.zip"`, or through Administration > Extensions, and confirm it with `bin/command extension --list`.
3. Create the AI model entry under Administration > Intelligence panel > Settings, selecting the `Custom OpenAI-compatible` provider, and enter the API credentials under Administration > Integrations.
4. Use `LITELLM_OPENAI_BASE_LOCAL_URL` as the base URL, `LITELLM_CHAT_MODEL` as the model name, and the role's own virtual key from `lookup('config', application_id, 'credentials.litellm_api_key')` as the API key. Re-add that credential to `meta/secrets.yml` and the `litellm` service to `meta/services.yml` in the same change, so the gateway mints the key only once a consumer presents it.

The field names on the provider record are only discoverable by unpacking the purchased artifact, so step 3 has to be measured against the extension actually installed rather than assumed from this note.

## Further Resources

- [EspoCRM Official Website](https://www.espocrm.com/) 🌍  
- [EspoCRM Documentation](https://docs.espocrm.com/) 📖  
- [Infinito.Nexus Project Repository](https://s.infinito.nexus/code) 🔗  
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/NzrEJNhCCr93QdFaj71yhY)

## Persona contract opt-outs

`biber` holds no EspoCRM role group, and every sign-in path admits only role-group members: with `sso` the role-group OIDC user provider refuses it, with LDAP only `ldapUserLoginFilter` refuses it, and without either no `biber` account exists. [`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore renders `PERSONA_BIBER_BLOCKED=true`. [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) asserts the refusal and adds `biber` to the `user`, `manager` and `administrator` groups in turn to assert the rights each one grants. The `administrator` and `guest` personas run in every variant.

## LDAP coverage

With `ldap` on and `sso` off, [`files/playwright/test-ldap-login.js`](./files/playwright/test-ldap-login.js) signs the platform administrator in through EspoCRM's own form, which binds against the directory, and [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) asserts that `ldapUserLoginFilter` refuses `biber`. `test-ldap-login.js` then adds `biber` to the `user` role group in the directory through `withLdapGroupMember` from the shared personas library, signs it in through the same form, asserts a regular EspoCRM user with the `Users` team whose call of the administration route ends on EspoCRM's 403 page, signs it out and removes the membership again.
