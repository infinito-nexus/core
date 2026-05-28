# Joomla

## Description

[Joomla](https://www.joomla.org/) is a free and open-source content management system that lets users build and run websites, intranets, and online applications without writing code. It exposes a component, module, and plugin architecture that authors and developers extend with custom content types, layouts, and integrations.

## Overview

This role deploys Joomla on Docker Compose. It builds a custom Joomla image that bakes in Composer for runtime extension builds, runs the Joomla CLI installer with the role's database, and installs the in-role `plg_system_keycloak` plugin so the site speaks OIDC against Keycloak with RBAC group mapping. A matrix-deploy variant flips the role to LDAP via Joomla's core LDAP authentication plugin instead.

For the OIDC plugin source and its environment contract see [README.md](./files/joomla-oidc-plugin/README.md).

## Features

- **Containerized deployment:** Run Joomla through Docker Compose with the role-specific custom image.
- **Native OIDC SSO:** Authenticate users against Keycloak via the in-role `plg_system_keycloak` plugin, with `?fallback=local` as an env-toggleable emergency hatch.
- **RBAC group mapping:** Map Keycloak group paths onto Joomla's built-in `Super Users`, `Editor`, and `Registered` user groups inside the plugin.
- **LDAP variant:** Switch to Joomla's core LDAP plugin via the role's matrix-deploy variant 1, for sites that prefer direct LDAP federation.
- **External database:** Persist Joomla content in the project's central RDBMS through the standard role-meta wiring.
- **NGINX reverse proxy:** Front the Joomla container with the project's `sys-stk-front-proxy` for TLS termination and per-domain routing.

## Developer Notes

See [README.md](./files/joomla-oidc-plugin/README.md) for the OIDC plugin's manifest, services provider, runtime environment, and route map.

## End-to-end tests

The Playwright spec at [files/playwright/playwright.spec.js](./files/playwright/playwright.spec.js) currently exercises the **administrator** path only: Keycloak SSO into the admin backend plus the local form-login emergency hatch (`?fallback=local`). The non-admin RBAC path via the canonical `biber` user is not yet covered.

Until the biber path is added:

- the role's [templates/playwright.env.j2](./templates/playwright.env.j2) MUST NOT carry stale `BIBER_USERNAME` / `BIBER_PASSWORD` keys (the lint at [tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py](../../tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py) enforces this);
- the admin scenarios stay gated on `oidc` (and on `ldap` for the LDAP-variant scenarios), so a deploy with `disable=oidc` reports the SSO scenario as `skipped`, never `failed`.

## Further Resources

- [Joomla Official Website](https://www.joomla.org/)
- [Joomla Documentation](https://docs.joomla.org/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
