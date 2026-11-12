# Matomo

## Description

Experience the power of Matomo, an innovative open-source analytics platform that delivers real-time insights, robust visitor tracking, and privacy-first features to elevate your website performance. Dive into actionable data with unmatched precision and clarity.

## Overview

This role deploys Matomo using Docker, automating the setup of your analytics platform along with its underlying database. With support for health checks, persistent storage for configuration and data, and integration with an NGINX reverse proxy, Matomo is configured to provide reliable and scalable analytics for your digital presence.

## Features

- **Real-Time Analytics:** Monitor visitor activity and generate detailed insights instantly.
- **Robust Tracking:** Track user interactions across your website with comprehensive analytics tools.
- **Privacy-First:** Enjoy a self-hosted solution that prioritizes data ownership and privacy.
- **Customizable Setup:** Configure database connections, admin credentials, and server settings via environment variables and Matomo's `config/config.ini.php`, which the role patches on every deploy.
- **Administrator Password:** The superuser password converges to the configured administrator's password on every deploy. An installed Matomo that lacks the configured administrator gets it as a further superuser next to the existing ones.
- **Single Sign-On:** With Keycloak deployed, the login page offers a Keycloak sign-in through the GPL-3.0 [RebelOIDC](https://github.com/Digitalist-Open-Cloud/Matomo-Plugin-RebelOIDC) plugin, which the custom image ships and the deploy activates. The OIDC username claim names the Matomo login, an existing account with that login is linked on first sign-in, and the sign-out also ends the Keycloak session. Signup is off, so only accounts the deploy provisioned can sign in. The local superuser keeps its password login behind the break-glass URL.
- **Login methods:** `services.matomo.login.method.*` of [meta/services.yml](./meta/services.yml) switches each sign-in method on its own. `sso` installs and activates RebelOIDC. `native` has no Matomo setting, so while it is off the injected [files/javascript/javascript.js](./files/javascript/javascript.js) hides the password form, together with its "Lost your password?" link, and the login page shows only the Keycloak entry. `2fa` activates Matomo's own TwoFactorAuth plugin while on and deactivates it while off; no account is forced to enroll. `login.method.2fa.enforced` defaults to `false` and has no effect in this role, `true` included, because the role renders no enforcement: TwoFactorAuth sends every request of an account it requires to set up a second factor to the setup page, API requests with a `token_auth` included, which would cut off the deploy's own `token_auth` calls of [tasks/07_config.yml](./tasks/07_config.yml). Matomo has no local self-registration.
- **Break-glass access:** the password form stays served while `native` is off, and `index.php?module=Login&fallback=local` shows it, so the local superuser signs in there while SSO is on. `files/playwright/auth.spec.js` signs the superuser in through that URL.
- **Role Mapping:** The RBAC roles `view`, `write` and `admin` grant that access on every tracked website, and `administrator` grants superuser access. [files/php/rbac_reconcile.php](./files/php/rbac_reconcile.php) creates an account for each member, assigns the access and takes it from every other account; the local superuser and the anonymous account are never touched. It runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and, with OpenLDAP deployed, on its timer, so a membership change and a website added later take effect within one timer interval.
- **Role Mapping At Sign-In:** The role-local plugin [files/php/infinito_rbac_login.php](./files/php/infinito_rbac_login.php) applies the same rules to the account that signs in through RebelOIDC, read from the `groups` claim of the ID token of that sign-in, so a role-group change and a website added later reach the account at its next sign-in instead of the next timer run. A sign-in without a `groups` claim changes nothing, a password login is never touched, and neither are the local superuser and the anonymous account. The deploy installs and activates the plugin together with RebelOIDC and writes its group paths to the `[InfinitoRbacLogin]` section of `config/config.ini.php`.
- **Proxy Scheme:** Matomo reads the scheme from `X-Forwarded-Proto`, so it builds `https` URLs behind the TLS-terminating proxy.
- **Corporate Design:** The InfinitoDesign theme plugin maps Matomo's theme colors onto the design tokens and ships the logo set; the administrator and the login page follow the browser color scheme. Both are removed when `design` is off.
- **Scalable Deployment:** Use Docker to ensure your analytics platform can grow with your traffic demands.
- **Version Upgrades:** When the pinned image ships a newer Matomo than the data volume holds, the deploy installs that release into the volume, keeps `config/config.ini.php`, `misc/user/` and Marketplace plugins, and runs `core:update`; a volume newer than the image stops the deploy.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to ([requirement 017](../../docs/requirements/017-playwright-biber-rbac-coverage.md)). A follow-up tightens them.

## Further Resources

- [Matomo Official Website](https://matomo.org/)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/8ox3o13gTQiCRE9nnvBPCB)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2`.

- **Administrator:** blocked only with `sso` off. The shared native login looks the username field up by the names `username`, `email` and `login`, while Matomo names it `form_login`, so the persona would submit the password alone. `files/playwright/auth.spec.js` drives the native form of the local superuser. With `sso` on the persona clicks the RebelOIDC button and signs in through Keycloak; `files/playwright/addons/rebeloidc.spec.js` additionally asserts the superuser access and the Keycloak sign-out.
- **Biber:** Matomo admits only members of its RBAC roles. Biber holds none, so the deploy provisions no account for biber and the Keycloak login ends without a Matomo session. `files/playwright/auth.spec.js` owns that deny-probe, the provider-side assertion the persona helpers no longer duplicate.
