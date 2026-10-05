# OpenCloud

## Description

[OpenCloud](https://opencloud.eu/) is a sovereign self-hosted file sync, share, and collaboration platform maintained by the Heinlein Group. It is a fork of the OpenCloud Infinite Scale codebase and is published as the `opencloudeu/opencloud` container image.

## Overview

This role deploys OpenCloud using Docker Compose in single-binary mode and exposes it under `open.cloud.{{ DOMAIN_PRIMARY }}` through the central reverse proxy. It wires the deployment to the shared Keycloak realm via OIDC, sources users and groups from the central `svc-db-openldap` directory, and runs side by side with `web-app-nextcloud` so both file platforms can coexist on the same host. For identity wiring details see [IAM.md](docs/IAM.md) and [LDAP.md](docs/LDAP.md).

## Features

- **Sovereign File Sync and Share:** Self-host file sync, shares, and collaborative spaces under your own domain.
- **Single Sign-On:** Users authenticate once via Keycloak and reuse the session across the platform.
- **Central User Directory:** Users and groups are read from a shared OpenLDAP backend, so accounts stay consistent across apps.
- **Auto-Provisioning:** New OIDC users are created on first login with username equal to the LDAP `uid`, and group claims drive role assignment.
- **OpenTalk Cross-Launch:** Start a video meeting in OpenTalk from a file context without re-authenticating when `web-app-opentalk` is deployed alongside.
- **Coexists with Nextcloud:** Runs in parallel with `web-app-nextcloud` on a distinct canonical hostname.

## Developer Notes

See [IAM.md](docs/IAM.md) for OIDC discovery and verification commands, and [LDAP.md](docs/LDAP.md) for the directory binding and schema mapping. Open follow-up items are tracked in [TODO.md](TODO.md).

## Further Resources

- [opencloud.eu](https://opencloud.eu/)
- [OpenCloud documentation](https://docs.opencloud.eu/)
- [opencloudeu/opencloud on Docker Hub](https://hub.docker.com/r/opencloudeu/opencloud)

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). OpenCloud Web answers Playwright's headless Chromium user agent with a "browser not supported" splash unless `forceAllowOldBrowser` is seeded into `localStorage` before the first navigation, and its OIDC callback runs through OpenCloud's own `/oidc-callback` → `/web-oidc-callback` routes instead of the oauth2-proxy pattern the shared helper detects. Both personas' Keycloak round trip is covered by [files/playwright/test-sso-login.js](./files/playwright/test-sso-login.js), which does that priming in [files/playwright/_shared.js](./files/playwright/_shared.js).
