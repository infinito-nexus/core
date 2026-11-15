# OpenCloud

## Description

[OpenCloud](https://opencloud.eu/) is a sovereign self-hosted file sync, share, and collaboration platform maintained by the Heinlein Group. It is a fork of the OpenCloud Infinite Scale codebase and is published as the `opencloudeu/opencloud` container image.

## Overview

This role deploys OpenCloud using Docker Compose in single-binary mode and exposes it under `open.cloud.{{ DOMAIN_PRIMARY }}` through the central reverse proxy. OpenCloud answers under one origin only, so on a node that also serves Tor it is published on its onion address alone. It wires the deployment to the shared Keycloak realm via OIDC, sources users and groups from the central `svc-db-openldap` directory, and runs side by side with `web-app-nextcloud` so both file platforms can coexist on the same host. For identity wiring details see [IAM.md](docs/IAM.md) and [LDAP.md](docs/LDAP.md).

## Features

- **Sovereign File Sync and Share:** Self-host file sync, shares, and collaborative spaces under your own domain.
- **Single Sign-On:** Users authenticate once via Keycloak and reuse the session across the platform.
- **Central User Directory:** Users and groups are read from a shared OpenLDAP backend, so accounts stay consistent across apps, and the display name comes from the directory full name.
- **Role Mapping:** With SSO, every login sets the OpenCloud role from the Keycloak realm roles: members of the `administrator`, `spaceadmin` and `guest` role groups become `admin`, `spaceadmin` and `user-light`, and every other realm user signs in as `user` through `default-roles-<realm>`. Without SSO, every account signs in as `user`.
- **Login methods:** `services.opencloud.login.method` declares `sso`, `ldap` and `native`. `sso` renders the `OC_OIDC_ISSUER` block of `templates/env.j2`, which points OpenCloud Web and the proxy at Keycloak. `ldap` and `native` both keep the built-in identity provider running (`OC_EXCLUDE_RUN_SERVICES=idp` is set only while both are off); it authenticates against the directory when `svc-db-openldap` is deployed and against the built-in IDM accounts otherwise, so LDAP mode admits no local account. OpenCloud has no own second factor and no self-registration. **Break-glass:** with SSO on no browser path admits the built-in `admin` account; administer the instance through the `opencloud` CLI inside the container, or set `login.method.sso.enabled: false` and `login.method.native.enabled: true` in the inventory and redeploy to get the built-in sign-in back.
- **OpenTalk Cross-Launch:** Start a video meeting in OpenTalk from a file context without re-authenticating when `web-app-opentalk` is deployed alongside.
- **Coexists with Nextcloud:** Runs in parallel with `web-app-nextcloud` on a distinct canonical hostname.

## Developer Notes

See [IAM.md](docs/IAM.md) for OIDC discovery and verification commands, and [LDAP.md](docs/LDAP.md) for the directory binding and schema mapping. Open follow-up items are tracked in [TODO.md](TODO.md).

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [opencloud.eu](https://opencloud.eu/)
- [OpenCloud documentation](https://docs.opencloud.eu/)
- [opencloudeu/opencloud on Docker Hub](https://hub.docker.com/r/opencloudeu/opencloud)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/PP8jVeTSNBXdJR1NGakVZN)

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). OpenCloud Web answers Playwright's headless Chromium user agent with a "browser not supported" splash unless `forceAllowOldBrowser` is seeded into `localStorage` before the first navigation, and its OIDC callback runs through OpenCloud's own `/oidc-callback` → `/web-oidc-callback` routes instead of the oauth2-proxy pattern the shared helper detects. Both personas' Keycloak round trip is covered by [files/playwright/test-sso-login.js](./files/playwright/test-sso-login.js), which does that priming in [files/playwright/_shared.js](./files/playwright/_shared.js).
