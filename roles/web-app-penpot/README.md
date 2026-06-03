# Penpot

## Description

Deploys [Penpot](https://penpot.app/), the open-source design and prototyping
platform (a self-hostable Figma alternative) for UI/UX design, real-time
collaboration, asset libraries, version history, and developer handoff — fully
integrated into the Infinito.Nexus ecosystem.

## Overview

The role brings up Penpot's containerized stack behind the standard
Infinito.Nexus reverse proxy and wires it into central identity, backup, and
dashboard infrastructure. It follows the per-role meta layout
([layout.md](../../docs/contributing/design/role/services/layout.md)) and is
modeled on [`web-app-openproject`](../web-app-openproject/) and
[`web-app-baserow`](../web-app-baserow/).

### Containers

| Service    | Image                  | Purpose                                                        |
|------------|------------------------|----------------------------------------------------------------|
| `frontend` | `penpotapp/frontend`   | Nginx + SPA; public HTTP surface, proxies to backend/exporter. |
| `backend`  | `penpotapp/backend`    | API, auth (OIDC/LDAP), persistence, asset storage.             |
| `exporter` | `penpotapp/exporter`   | Headless renderer for SVG/PDF/image export and dev handoff.    |
| `redis`    | shared `svc-db-redis`  | Cache / pub-sub for real-time collaboration.                   |
| `postgres` | shared `svc-db-postgres` | Relational store.                                            |

The **exporter** is mandatory: it backs the export (SVG/PDF) and developer
handoff features.

## Features

- Design creation and editing, team collaboration with comments and live cursors.
- Shared asset libraries and components, version history.
- Export (SVG, PDF, images) and developer handoff (CSS/code) via the exporter.
- Real-time collaboration over WebSockets through the proxy.

## Identity

Login methods are toggled through `PENPOT_FLAGS` and configured by Ansible:

- **OIDC** via [`web-app-keycloak`](../web-app-keycloak/) — enabled when the
  `sso` service is active (`flavor: oidc`, native in-app login). Adds
  `enable-login-with-oidc`.
- **LDAP** via [`svc-db-openldap`](../svc-db-openldap/) — enabled when the
  `ldap` service is active. Adds `enable-login-with-ldap`.

Local registration / password login stay on as the baseline account tier.

## Storage & scalability

- Assets are stored on the filesystem backend (`PENPOT_ASSETS_STORAGE_BACKEND=assets-fs`)
  on the backup-ready named volume `penpot_assets`, mounted into both `frontend`
  and `backend` at `/opt/data/assets`.
- The PostgreSQL database is backed up by the central backup roles; the asset
  volume is backup-ready by convention.
- **S3-compatible object storage (future):** Penpot supports an `assets-s3`
  backend (`PENPOT_STORAGE_ASSETS_FS_*` → `PENPOT_STORAGE_ASSETS_S3_*`). It is
  intentionally **not** implemented here; switching the backend and adding the
  S3 credentials to `meta/schema.yml` is the documented upgrade path.

## Ports & networking

- Local proxy bind: `services.penpot.ports.local.http` (`8041`).
- Role network: `192.168.105.176/28`.

## Autonomous-implementation notes

Resolved by best judgement during the autonomous build (per the requirement's
Procedure); revisit at PR review:

- **Image tag** pinned to `2.5.4` for all three containers (single upstream tag).
- **Exporter `PENPOT_PUBLIC_URI`** is shared from the single role env file (the
  external HTTPS base URL). Penpot upstream also supports an internal
  `http://frontend:8080` value; the shared-env contract renders one file for all
  containers, which the upstream image tolerates.
- **CSP** allows `unsafe-inline`/`unsafe-eval` for `script-src-elem` and
  `blob:` workers/images, required by Penpot's SPA and worker-based renderer.

## Verification status

`make test` (lint + integration suites) is the static gate exercised here. The
live Definition-of-Done items — one-command deploy on a fresh host, reachability
at the generated domain, and live OIDC/LDAP Playwright flows against a running
Keycloak/OpenLDAP — require a real deployment target and are validated during a
matrix deploy, not by the static suite.

## Further Resources

- [Penpot Official Website](https://penpot.app/)
- [Penpot Configuration Guide](https://help.penpot.app/technical-guide/configuration/)
- [Penpot Docker Guide](https://github.com/penpot/penpot/tree/main/docker)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
