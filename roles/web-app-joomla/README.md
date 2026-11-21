# Joomla

## Description

[Joomla](https://www.joomla.org/) is a free and open-source content management system that lets users build and run websites, intranets, and online applications without writing code. It exposes a component, module, and plugin architecture that authors and developers extend with custom content types, layouts, and integrations.

## Overview

This role deploys Joomla on Docker Compose. It builds a custom Joomla image that bakes in Composer for runtime extension builds, runs the Joomla CLI installer with the role's database, and installs the in-role `plg_system_keycloak` plugin so the site speaks OIDC against Keycloak with RBAC group mapping. A matrix-deploy variant flips the role to LDAP via Joomla's core LDAP authentication plugin instead.

For the OIDC plugin source and its environment contract see [README.md](./files/joomla-oidc-plugin/README.md).

## Addons

Role-level extensions are declared in `meta/addons/`
(unified addon contract, requirement 026):

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `plg_system_keycloak` | `plugin` | enabled with `services.joomla.login.method.sso`, which is on whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |

`plg_system_keycloak` is built imperatively inside the Joomla container and speaks OIDC against Keycloak.
Its enablement derives from the `sso` login method, and its OIDC runtime contract (issuer, client id/secret, redirect/end-session URLs, fallback toggle, and RBAC group paths) lives under the addon's `config:` block, which [`templates/env.j2`](./templates/env.j2) renders into the `JOOMLA_OIDC_*` plugin environment.

## Features

- **Containerized deployment:** Run Joomla through Docker Compose with the role-specific custom image.
- **Native OIDC SSO:** Authenticate users against Keycloak via the in-role `plg_system_keycloak` plugin, with `?fallback=local` as an env-toggleable emergency hatch.
- **Login methods:** `services.joomla.login.method` declares `sso`, `ldap`, `native`, `2fa`, `passkey` and `registration` (see [Login Methods](../../docs/contributing/design/iam/login.md)). `sso` enables `plg_system_keycloak`, which sends every guest to Keycloak. `ldap` enables `plg_authentication_ldap` ([`tasks/10_ldap.yml`](./tasks/10_ldap.yml)). [`tasks/11_login_methods.yml`](./tasks/11_login_methods.yml) runs [`files/php/login_methods.php`](./files/php/login_methods.php) on every deploy, which sets `plg_authentication_joomla` from `native`, `plg_system_webauthn` (the passkey button) from `passkey`, the `totp`, `yubikey`, `webauthn` and `email` plugins of the `multifactorauth` group from `2fa`, and the com_users `allowUserRegistration` param from `registration`. While `2fa` is on, `login.method.2fa.enforced` (default `true`) sets the com_users `forceMFAUserGroups` param to the root user group `Public` (`JOOMLA_ROOT_USER_GROUP`), which every account inherits, Super Users included, so an account without a second factor sets one up at its next sign-in; `enforced: false` empties the list. While `2fa` is off the deploy disables every `multifactorauth` plugin, and Joomla would send a forced account to a methods page that offers nothing, so the same run empties the list, also one an admin chose, once no plugin of the `multifactorauth` group is enabled any more; while one still is, such as `fixed` or a third-party method an admin enabled, the list stays. Joomla enforces it only in the site and administrator applications, so the CLI and the Web Services API stay reachable. Break-glass for an account locked out by a forced list without an enabled method, with `<prefix>` the `$dbprefix` of `configuration.php`: on MariaDB `UPDATE <prefix>extensions SET params = JSON_SET(params, '$.forceMFAUserGroups', JSON_ARRAY()) WHERE type = 'component' AND element = 'com_users';`, on PostgreSQL `UPDATE <prefix>extensions SET params = jsonb_set(params::jsonb, '{forceMFAUserGroups}', '[]')::text WHERE type = 'component' AND element = 'com_users';`, then `php cli/joomla.php cache:clean`. Shared form: Joomla's authentication plugins apply to every account, so Joomla cannot tell local from directory accounts; `plg_authentication_joomla` therefore stays on while `ldap` is on or the break-glass needs it, and `native` off removes local accounts from the form only when neither applies.
- **Break-glass access:** with SSO on, `services.sso.oidc.fallback_enabled` keeps `/administrator/index.php?fallback=local` and `index.php?option=com_users&view=login&fallback=local` on the local form for ten minutes, and `plg_authentication_joomla` stays enabled for it; the bootstrap administrator signs in there with its local password ([`test-oidc-fallback.js`](./files/playwright/test-oidc-fallback.js)).
- **RBAC group mapping:** Map the Keycloak groups of the `administrator`, `manager`, `publisher`, `editor`, `author` and `registered` roles onto Joomla's built-in `Super Users`, `Manager`, `Publisher`, `Editor`, `Author` and `Registered` user groups on every login.
- **Open access:** Let every realm user sign in; a user without a mapped role group lands in the com_users "New User Registration Group" (`Registered`).
- **Profile sync:** Overwrite name, email, frontend language (from the `locale` claim, resolved to an installed site language) and time zone (from the `zoneinfo` claim) on every login, so Keycloak stays the source of truth.
- **Contact sync:** Enable the core `plg_user_profile` and overwrite its phone, street, city, region, postal code, country and website fields from the `phone_number`, `address` and `website` claims on every login; the plugin requests the `phone` and `address` scopes, and the profile form hides the profile fields Keycloak does not feed.
- **Read-only IdP fields:** the `sso.<claim>` fields of [`meta/forms.yml`](./meta/forms.yml) decide which fields are locked. [`templates/env.j2`](./templates/env.j2) renders their keys into `JOOMLA_OIDC_PROFILE_LOCKED` through `lookup('field_locks', application_id).profile`, and for an SSO account the plugin renders exactly those fields read-only in the com_users profile form and keeps their stored values when a profile save carries others. `onUserBeforeSave` refuses every other change of a locked field or of the SSO marker of an SSO account from a site request or from the web services API. The shared lock renderer of `sys-front-inj-javascript` adds the translated warning to the same fields as their hover title. Removing such a field unlocks it in the form and on save; the next login still overwrites it.
- **SSO-only sign-in:** a local sign-in (password, directory, passkey or remember-me cookie) of an SSO account other than the bootstrap administrator is signed out again at once and sent to Keycloak, so a local password set through a password reset or by an administrator never opens a session that skips the login sync of groups and profile.
- **Break-glass editing:** the backend is break-glass only, and so is a local site session of the bootstrap administrator or of an account holding `core.admin`, signed in with a password through `?fallback=local`: they edit every field of every account, and the next Keycloak login of an SSO account overwrites what Keycloak manages again. The console (`cli/joomla.php`) is not guarded either.
- **SSO logout:** Route a com_users Log out request through Keycloak's end-session endpoint, so signing out of Joomla also ends the Keycloak session; with the `logout` service on, its injected script sends the button to the universal logout first.
- **LDAP variant:** Configure and enable Joomla's core `plg_authentication_ldap` against `svc-db-openldap` whenever the `ldap` login method is on (the `ldap` service without `sso`, variant 1), binding with the directory administrator, searching users by their login attribute and reading full name and email from the directory; new directory users are created in `Registered`. The `ldap` form of [`meta/forms.yml`](./meta/forms.yml) declares these plugin parameters with their values in `services.joomla.ldap` of [`meta/services.yml`](./meta/services.yml). [`files/php/ldap_plugin.php`](./files/php/ldap_plugin.php) reads the stored parameters first, the deploy log and the journal report each parameter it reverts, and the plugin row is written only while a parameter, the bind password or the plugin state differs. The shared renderer of `sys-front-inj-javascript` shows the parameters read-only on the plugin's edit page, and a double-click unlocks one after a confirmation; the bind password is written but never shown or locked.
- **External database:** Persist Joomla content in the project's central RDBMS through the standard role-meta wiring.
- **NGINX reverse proxy:** Front the Joomla container with the project's [`svc-stack`](../svc-stack/README.md) for TLS termination and per-domain routing.

## Developer Notes

See [README.md](./files/joomla-oidc-plugin/README.md) for the OIDC plugin's manifest, services provider, runtime environment, and route map.

## End-to-end tests

The Playwright spec at [`playwright.spec.js`](./files/playwright/playwright.spec.js) covers:

- the administrator's Keycloak SSO handshake and the local form-login emergency hatch (`?fallback=local`);
- `biber` in each of the `administrator`, `manager`, `publisher`, `editor`, `author` and `registered` groups landing in the matching Joomla group, the bootstrap administrator keeping `Super Users` without the `administrator` group, and `biber` without a role group landing in `Registered`, read from Users: Manage ([`test-rbac-groups.js`](./files/playwright/test-rbac-groups.js));
- the `locale`, `zoneinfo`, phone, address and website Keycloak attributes of `biber` arriving as Joomla language, time zone and `plg_user_profile` fields, every synced field read-only, and a save with a tampered name keeping the Keycloak name ([`test-profile-sync.js`](./files/playwright/test-profile-sync.js));
- every `sso.<claim>` field of `meta/forms.yml` read-only for `biber` with the translated warning, a direct profile POST with other values keeping them while saving the unmanaged editor setting, the SSO administrator unable to rename itself, a local break-glass session editing its own profile and its account in the backend, and a local password on `biber` opening no `?fallback=local` session ([`test-profile-lock.js`](./files/playwright/test-profile-lock.js));
- the com_users Log out button ending the Keycloak session, through the issuer's end-session endpoint when `logout` is off and through the universal logout otherwise ([`test-sso-logout.js`](./files/playwright/test-sso-logout.js));
- the administrator and `biber` signing in through the core LDAP plugin in the LDAP variant with SSO off ([`test-ldap-login.js`](./files/playwright/test-ldap-login.js)), and `plg_authentication_ldap` staying disabled in Extensions: Plugins while `ldap` is off ([`test-ldap-disabled.js`](./files/playwright/test-ldap-disabled.js));
- with SSO on, the site and administrator sign-in sending a guest to Keycloak, and the `?fallback=local` forms showing no passkey or registration entry while those methods are off ([`test-login-methods.js`](./files/playwright/test-login-methods.js)).

SSO scenarios are gated on `sso` and LDAP scenarios on `ldap`, so a deploy without the service reports them as `skipped`, never `failed`.

## Further Resources

- [Joomla Official Website](https://www.joomla.org/)
- [Joomla Documentation](https://docs.joomla.org/)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/WcX6mKb6zbJMTtrk47XCNk)

## Persona contract opt-outs

The shared `biber` and `administrator` persona journeys are opted out via `PERSONA_BIBER_BLOCKED` / `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`.
The site front page renders no logout control: Joomla's site template places no login module, and the only rendered Log out button sits on the com_users login view, so the persona's mandatory in-app logout click on the front page has no target and navigating a logout URL directly is forbidden by the contract.
The OIDC handshake itself, the Keycloak logout from the com_users Log out button, the LDAP variant and the `/administrator?fallback=local` hatch are covered by `files/playwright/test-oidc-login.js`, `test-sso-logout.js`, `test-ldap-login.js` and `test-oidc-fallback.js`.
