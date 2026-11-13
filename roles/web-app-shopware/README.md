# Shopware

## Description

Empower your e-commerce vision with **Shopware 6**, a modern, flexible, and open-source commerce platform built on **Symfony and Vue.js**. Designed for growth and innovation, it enables seamless integration, outstanding customer experiences, and complete control over your digital business. Build, scale, and sell with confidence.

## Overview

This role deploys **Shopware 6** using **Docker**. It automates installation, migration, and configuration of your storefront, integrating with a central **MariaDB** database.
Optional components like **Redis** and **OpenSearch** enhance performance and search capabilities, while **OIDC** integrates the administration backend with **Keycloak**. Directory accounts sign in the same way: Shopware has no admin-LDAP extension this role can install, so LDAP identities arrive through Keycloak's user federation rather than through a plugin of their own.

With automated setup, update handling, variable management, and plugin-based authentication, this role simplifies the deployment and maintenance of your Shopware instance.

## Features

- **Modern and Scalable:** A robust Symfony-based framework optimized for commerce innovation.
- **Automated Setup & Maintenance:** Installs, migrates, and configures Shopware automatically.
- **Version Upgrades:** When the image ships another Shopware than the version recorded in `deployment.version`, the init container runs `system:update:finish` and the plugin updates once, then records the new version.
- **Extensible Architecture:** Optional Redis, OpenSearch, and plugin-based IAM integrations.
- **Memory-map floor:** the bundled OpenSearch gets `vm.max_map_count: 262144` (`SHOPWARE_SYSCTL_PARAMETERS`) through [sys-sysctl](../sys-sysctl/), persisted in `/etc/sysctl.d/99-shopware.conf`; the key is host-global, so it is skipped inside a container.
- **Centralized Database Access:** Connects seamlessly to the shared MariaDB service.
- **Integrated Configuration:** Environment and Docker Compose variables managed automatically.
- **Group-Based Admin Roles:** [`files/php/oidc/client.php`](./files/php/oidc/client.php) keeps two AdminOpenAuth role-assignment rules whose ID token condition reads the groups claim: members of the `administrator` group become Shopware administrators, members of the `editor` group get the `Editor` ACL role (products, categories, media and shopping experiences, privileges in `SHOPWARE_ACL_EDITOR_PRIVILEGES`). Every other rule of the Keycloak client is deleted. [`files/php/oidc/admins.php`](./files/php/oidc/admins.php) withdraws the admin flag from Keycloak-linked users outside the `administrator` group and the `Editor` ACL role from Keycloak-linked users outside the `editor` group, the platform administrator excepted; it runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer.
- **Role-Group Sign-In:** [`files/php/oidc/role_gate.php`](./files/php/oidc/role_gate.php), mounted at `src/InfinitoRbac/AdminOpenAuthRoleGate.php` and registered in [`templates/adminopenauth.yaml.j2`](./templates/adminopenauth.yaml.j2) as a listener of AdminOpenAuth's `UserRedirectReceivedEvent` after the rule execution, answers `403` to a Keycloak sign-in that no role-assignment rule granted the admin flag or an ACL role. Shopware creates no account for such a user.
- **Login methods:** `services.shopware.login.method.*` of [meta/services.yml](./meta/services.yml) switches each sign-in method of the administration on its own. `sso` sets the `login` flag of the AdminOpenAuth Keycloak client in [`files/php/oidc/client.php`](./files/php/oidc/client.php). `native` sets AdminOpenAuth's `denyPasswordLogin` while it is off, which hides the password form and its "forgot password" link; `enableAutoRedirect` (`services.shopware.admin_auto_redirect`) stays off, so the login page shows the Keycloak entry instead of jumping to Keycloak. The administration has no LDAP sign-in, no second factor and no self-registration of its own.
- **Managed settings:** [meta/forms.yml](./meta/forms.yml) declares both forms the deploy owns. `plugin_config` renders `denyPasswordLogin` and `enableAutoRedirect` as static system config (`shopware.system_config.default`) into [`templates/adminopenauth.yaml.j2`](./templates/adminopenauth.yaml.j2): Shopware's `SystemConfigService::setMultiple` refuses every differing write of those keys, and [`files/php/oidc/static_config_lock.php`](./files/php/oidc/static_config_lock.php), mounted at `src/InfinitoRbac/StaticSystemConfigLock.php`, marks each static key `disabled` in the settings schema, so the extension settings show it greyed out. `client` covers the switches and provider endpoints of the Keycloak client row, which [`files/php/oidc/client.php`](./files/php/oidc/client.php) reads before it writes them back; each edit the deploy reverts lands in the drift report. AdminOpenAuth's client page gives its fields no stable `name`, so that form has no lock yet.
- **Break-glass access:** `denyPasswordLogin` only hides the form, so the local administrator's password grant (`POST /api/oauth/token` with `client_id: administration` and `grant_type: password`) keeps working while SSO is on; the deploy itself uses it in [`files/php/oidc/client.php`](./files/php/oidc/client.php). The form comes back with `services.shopware.login.method.native.enabled: true` in the inventory and a deploy; `system:config:set` refuses the key while it is static.
- **Editor Privilege Check:** `SHOPWARE_ACL_EDITOR_PRIVILEGES` is the expansion of the `product`, `category`, `media` and `cms` permission keys, which the administration computes in JavaScript only (`getPrivilegesForAdminPrivilegeKeys` in `app/service/privileges.service.ts`). [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) expands the keys of the deployed `Editor` role in the signed-in administration and fails with the missing privileges when a Shopware version grants more than the list.

## Further Resources

- [Shopware Official Website](https://www.shopware.com/en/) <!-- nocheck: url; redirect loop on probe, site is alive when visited interactively -->
- [Shopware Developer Documentation](https://developer.shopware.com/)
- [Shopware Store (Plugins)](https://store.shopware.com/en/)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/TLzWb6b51sQTvihCdbdXbT)

## Persona contract opt-outs

[`tasks/01_admin.yml`](./tasks/01_admin.yml) provisions only the administrator in Shopware's user table. [`meta/services.yml`](./meta/services.yml) pins `services.sso.flavor: oidc`, so no oauth2-proxy fronts the role and the storefront carries no authenticated surface at all; the Keycloak login provider that [`tasks/setup/oidc.yml`](./tasks/setup/oidc.yml) configures covers the administration backend alone. `biber` therefore has no storefront account in any matrix variant and [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` unconditionally. [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) asserts that its backend sign-in through Keycloak is refused without a group and admitted with the `Editor` ACL role as a member of the `editor` group.

`PERSONA_ADMINISTRATOR_BLOCKED=true` is declared because the shared helper cannot reach Shopware's logout, not because the journey is untestable. The only logout control lives in `.sw-admin-menu__user-actions`, which the administration stylesheet keeps at `display: none` until its toggle is clicked, and that toggle is a bare `div` carrying no role, no `aria-haspopup` and no dropdown class — nothing in the helper's trigger set matches it. Its second fallback, following a same-origin settings link, misses as well because the administration is hash-routed and every settings target is `#/sw/settings/...`.

The journey itself is not dropped. [`files/playwright/test-admin-native.js`](./files/playwright/test-admin-native.js) drives it through Shopware's own selectors: an authenticated backend assertion, then logout through the user-actions toggle and back to the login page. `SSO_SERVICE_ENABLED` selects how it signs in — through the `a.heptacom-admin-open-auth--button` provider link that AdminOpenAuth appends into `.sw-login__content` when SSO is on, through the native password form when it is off. The `guest` persona and the role-local reachability, TLS and HSTS assertions run unconditionally.

## LDAP coverage

No Playwright scenario gates on `ldap`, and [`templates/playwright.env.j2`](./templates/playwright.env.j2) suppresses the service-gate check for `LDAP_SERVICE_ENABLED`. Shopware has no LDAP sign-in of its own and the role installs no admin-LDAP extension, so there is no LDAP-bind surface to drive: with `sso` on, directory accounts reach the administration through Keycloak's user federation and the AdminOpenAuth provider, which [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) covers; with `sso` off, no directory account reaches Shopware.
