# Shopware

## Description

Empower your e-commerce vision with **Shopware 6**, a modern, flexible, and open-source commerce platform built on **Symfony and Vue.js**. Designed for growth and innovation, it enables seamless integration, outstanding customer experiences, and complete control over your digital business. Build, scale, and sell with confidence.

## Overview

This role deploys **Shopware 6** using **Docker**. It automates installation, migration, and configuration of your storefront, integrating with a central **MariaDB** database.
Optional components like **Redis** and **OpenSearch** enhance performance and search capabilities, while **OIDC** integrates the administration backend with **Keycloak**. Directory accounts sign in the same way: Shopware has no admin-LDAP extension this role can install, so LDAP identities arrive through Keycloak's user federation rather than through a plugin of their own.

With automated setup, update handling, variable management, and plugin-based authentication, this role simplifies the deployment and maintenance of your Shopware instance.

## Features

* **Modern and Scalable:** A robust Symfony-based framework optimized for commerce innovation.
* **Automated Setup & Maintenance:** Installs, migrates, and configures Shopware automatically.
* **Extensible Architecture:** Optional Redis, OpenSearch, and plugin-based IAM integrations.
* **Centralized Database Access:** Connects seamlessly to the shared MariaDB service.
* **Integrated Configuration:** Environment and Docker Compose variables managed automatically.

## Further Resources

* [Shopware Official Website](https://www.shopware.com/en/) <!-- nocheck: url; redirect loop on probe, site is alive when visited interactively -->
* [Shopware Developer Documentation](https://developer.shopware.com/)
* [Shopware Store (Plugins)](https://store.shopware.com/en/)

## Persona contract opt-outs

[`tasks/01_admin.yml`](./tasks/01_admin.yml) provisions only the administrator in Shopware's user table. [`meta/services.yml`](./meta/services.yml) pins `services.sso.flavor: oidc`, so no oauth2-proxy fronts the role and the storefront carries no authenticated surface at all; the Keycloak login provider that [`tasks/setup/oidc.yml`](./tasks/setup/oidc.yml) configures covers the administration backend alone. `biber` therefore has no account in any matrix variant and [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` unconditionally.

`PERSONA_ADMINISTRATOR_BLOCKED=true` is declared because the shared helper cannot reach Shopware's logout, not because the journey is untestable. The only logout control lives in `.sw-admin-menu__user-actions`, which the administration stylesheet keeps at `display: none` until its toggle is clicked, and that toggle is a bare `div` carrying no role, no `aria-haspopup` and no dropdown class — nothing in the helper's trigger set matches it. Its second fallback, following a same-origin settings link, misses as well because the administration is hash-routed and every settings target is `#/sw/settings/...`.

The journey itself is not dropped. [`files/playwright/test-admin-native.js`](./files/playwright/test-admin-native.js) drives it through Shopware's own selectors: an authenticated backend assertion, then logout through the user-actions toggle and back to the login form. `SSO_SERVICE_ENABLED` selects how it signs in — through the `a.heptacom-admin-open-auth--button` provider link that AdminOpenAuth appends into `.sw-login__content` when SSO is on, through the native password form when it is off. The `guest` persona and the role-local reachability, TLS and HSTS assertions run unconditionally.
