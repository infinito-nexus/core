# Pixelfed

## Description

Pixelfed is a decentralized image-sharing platform that champions creativity and privacy. It offers a secure, community-driven alternative to centralized social networks by enabling federated communication and seamless content sharing through a modern web interface.

## Overview

This Docker Compose deployment automates the installation and operation of a Pixelfed instance.

## Features

- **Decentralized Content Sharing:** Empower users to share photos and visual content across an interoperable, federated network with enhanced privacy controls.
- **Modern, Responsive Web Interface:** Access an intuitive and adaptive UI for effortless browsing, administration, and content management.
- **Robust Scalability & Performance:** Leverage integrated Redis caching and a reliable database (MariaDB or PostgreSQL) for smooth scaling and high performance.
- **Flexible Configuration:** Customize cache sizes, domain settings, and authentication options via environment variables and templated configuration files.
- **Maintenance & Administration Tools:** Built-in CLI and web-app-based tools to clear caches, manage the database, and monitor application health.
- **Single Sign-On (SSO) / OpenID Connect (OIDC):** Seamless integration with external identity providers for centralized authentication.
- **Login methods:** `services.pixelfed.login.method` declares `sso`, `native`, `2fa` and `registration`; Pixelfed has no LDAP or passkey. `sso` sets `PF_OIDC_ENABLED`, which shows "Sign-in with OIDC", and `registration` sets `OPEN_REGISTRATION`, which shows the sign-up link ([templates/env.j2](./templates/env.j2)). Pixelfed has no setting for its password form or its two-factor enrollment, so [templates/javascript.js.j2](./templates/javascript.js.j2), injected through the `javascript` service whenever `native` or `2fa` is off, hides the email and password form on `/login` while `native` is off and the "Enable two-factor authentication" entry under `/settings/security` while `2fa` is off; both still answer on the server. Pixelfed has no setting that requires a second factor, so `login.method.2fa.enforced` only offers it here.
- **Break-glass path:** `/login?fallback=local` keeps the password form while `native` is off, so the administrator created through artisan signs in with its e-mail address and password when Keycloak is unavailable.
- **Admin Flag From RBAC:** [files/python/rbac_sync.py](./files/python/rbac_sync.py) sets the Pixelfed admin flag on the members of the `administrator` role group, matched by username, e-mail or OIDC mapping, and clears it on every other account. It runs as a host hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) against the database container at every deploy and on its timer. With `sso`, the listener [files/php/rbac/oidc_login.php](./files/php/rbac/oidc_login.php), mounted into `app/Listeners` where Laravel's event discovery registers it, applies the same flag at every OIDC sign-in from the `administrator` group in the groups claim, which [files/php/rbac/userinfo_client.php](./files/php/rbac/userinfo_client.php) reads off the userinfo response on its way through `UserOidcService`; a group change therefore reaches the account at its next sign-in, and a new member holds the flag from its first one. The administrator created through artisan keeps the flag.

## Further Resources

- [Official Pixelfed website](https://pixelfed.org/)
- [Pixelfed GitHub repository](https://github.com/pixelfed/pixelfed)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/NZHqJBSryezaKba1jskYaZ)

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). Pixelfed's login id is the account e-mail rather than the Keycloak username, and the artisan-bootstrapped administrator name is reserved, so pixelfed's first-time OIDC registration cannot mint it either. `biber` additionally needs his Keycloak e-mail rewritten to a resolvable domain through the Keycloak admin API before the first OIDC login, because pixelfed's `dns,spoof` validator rejects `.example` addresses. Both setups live in [files/playwright/_shared.js](./files/playwright/_shared.js) and drive the dedicated login specs in `files/playwright/`.
