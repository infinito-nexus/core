# n8n

## Description

[n8n](https://n8n.io/) is an open-source workflow automation platform. Connect services, transform data, and build integrations using a visual low-code editor or custom JavaScript/Python nodes.

## Overview

This role deploys n8n Community Edition using the upstream `docker.n8n.io/n8nio/n8n` image backed by a PostgreSQL database (consumed from the central `svc-db-postgres` via `sys-stk-full`). Authentication is handled by an **oauth2-proxy** sidecar (Keycloak OIDC) in V1, n8n's built-in LDAP in V3, or left to n8n's own user-management UI in V2. Credentials stored inside n8n are encrypted at rest with a stable `N8N_ENCRYPTION_KEY`.

## Features

- **Visual workflow editor:** Drag-and-drop canvas with 400+ built-in integrations.
- **Webhook triggers:** Expose workflow endpoints for external systems to call.
- **SSO via oauth2-proxy:** V1 gates all access through the shared Keycloak OIDC client (oauth2-proxy edge); n8n itself sees only already-authenticated requests.
- **LDAP authentication:** V3 wires n8n's built-in LDAP support to `svc-db-openldap`.
- **Encrypted credential storage:** `N8N_ENCRYPTION_KEY` protects all saved credentials at rest; the key is stable across re-deploys.
- **Postgres backend:** Workflow definitions, execution history, and user data persist in the central `svc-db-postgres`.

## Variant Matrix

| | V1 (sso+ldap) | V2 (no auth) | V3 (ldap only) |
|---|---|---|---|
| oauth2-proxy SSO | ✓ | ✗ | ✗ |
| LDAP | ✓ | ✗ | ✓ |
| Shared postgres | ✓ | ✗ | ✗ |

## First-Run Setup

n8n CE requires an owner account to be created on first access. After deployment, navigate to the canonical URL and complete the owner setup wizard. In V1, the wizard is presented after the oauth2-proxy SSO gate, so only Keycloak-authenticated users can reach it.

## Developer Notes

Variant matrix: [variants.yml](./meta/variants.yml). Service flags and image pin: [services.yml](./meta/services.yml). Credentials declared in [schema.yml](./meta/schema.yml).

## Further Resources

- [n8n Official Website](https://n8n.io/)
- [n8n Docker Documentation](https://docs.n8n.io/hosting/installation/docker/)
- [n8n GitHub](https://github.com/n8n-io/n8n)

## Credits

Developed and maintained by **Prageeth Panicker**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
