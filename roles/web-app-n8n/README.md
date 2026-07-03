# n8n

## Description

[n8n](https://n8n.io/) is an open-source workflow automation platform. Connect services, transform data, and build integrations using a visual low-code editor or custom JavaScript/Python nodes.

## Overview

This role deploys n8n Community Edition using the upstream `docker.n8n.io/n8nio/n8n` image backed by a PostgreSQL database (consumed from the central `svc-db-postgres` via `sys-stk-full`). Authentication is handled by an **oauth2-proxy** sidecar (Keycloak OIDC) in V1, or left to n8n's own user-management UI in V2. n8n Community Edition does not support LDAP — it is gated behind n8n's Enterprise license (`ldap.controller.ee.js` is not registered in CE) — so no LDAP variant is offered. Credentials stored inside n8n are encrypted at rest with a stable `N8N_ENCRYPTION_KEY`.

## Features

- **Visual workflow editor:** Drag-and-drop canvas with 400+ built-in integrations.
- **Webhook triggers:** Expose workflow endpoints for external systems to call.
- **SSO via oauth2-proxy:** V1 gates all access through the shared Keycloak OIDC client (oauth2-proxy edge). n8n Community Edition (`authenticationMethod=email`) does not accept that edge session as its own, so every request still lands on n8n's native login form behind the gate.
- **Encrypted credential storage:** `N8N_ENCRYPTION_KEY` protects all saved credentials at rest; the key is stable across re-deploys.
- **Postgres backend:** Workflow definitions, execution history, and user data persist in the central `svc-db-postgres`.

## Variant Matrix

| | V1 (sso) | V2 (no auth) |
|---|---|---|
| oauth2-proxy SSO | ✓ | ✗ |
| Shared postgres | ✓ | ✗ |

## First-Run Setup

The deployment bootstrap (`tasks/02_bootstrap.yml`) automatically creates the owner account on first run using the platform-generated `owner_password` credential. No manual wizard step is required.

**V1 (SSO):** The oauth2-proxy edge gate redirects all requests to Keycloak. Passing Keycloak SSO only proves identity at the edge — n8n itself has no concept of that session, so the browser still lands on n8n's own login form. Only the owner account (`users.administrator.email` + the break-glass `owner_password`) is provisioned inside n8n, so the administrator persona completes that second login with the owner credential. Regular Keycloak users are validated at the SSO edge (oauth2-proxy accepts the request) but have no n8n-local account and therefore cannot reach n8n's own workflow surface in V1.

**V2 (no auth):** n8n presents its native login UI. The administrator logs in with the email configured in `users.administrator.email` and the password stored in the platform credential `credentials.owner_password`. Retrieve it with:

```
ansible-vault view group_vars/web-app-n8n.yml
```

## Developer Notes

Variant matrix: [variants.yml](./meta/variants.yml). Service flags and image pin: [services.yml](./meta/services.yml). Credentials declared in [schema.yml](./meta/schema.yml).

## Further Resources

- [n8n Official Website](https://n8n.io/)
- [n8n Docker Documentation](https://docs.n8n.io/hosting/installation/docker/)
- [n8n GitHub](https://github.com/n8n-io/n8n)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
