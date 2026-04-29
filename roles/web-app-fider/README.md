# Fider

## Description

[Fider](https://getfider.com/) is an open-source community feedback and voting platform that allows teams to collect, prioritize, and track feature requests and ideas.

## Overview

This role deploys Fider as part of the Infinito.Nexus stack using a single Docker Compose container backed by PostgreSQL. It configures SSO via Keycloak automatically on first deploy, optional email notifications via Mailu, and HTTPS via NGINX reverse proxy.

The setup tasks handle the full first-deploy bootstrap automatically:

1. **Tenant bootstrap:** calls Fider's `POST /_api/tenants` API to create the initial tenant.
2. **Admin user creation:** inserts the admin user directly into the `users` table, bypassing email verification. Idempotent via `WHERE NOT EXISTS`.
3. **Tenant activation:** sets `status=1` on the tenant row so Fider serves the public page.
4. **OIDC provider:** inserts the Keycloak provider into `oauth_providers`. Idempotent via `ON CONFLICT (tenant_id, provider) DO UPDATE`.

When a user logs in via Keycloak for the first time, Fider matches their email to the existing admin user and links the OIDC provider automatically. To enable SSO, set `services.oidc.enabled: true` (the default) and ensure `OIDC.CLIENT.SECRET` is configured.

## Features

- **Single-container deployment** via Docker Compose.
- **PostgreSQL database:** all data including attachments stored in the database, no extra volumes needed.
- **SSO via Keycloak:** configured automatically on first deploy.
- **Email notifications** via Mailu (optional).
- **HTTPS** enforced via NGINX reverse proxy.

## Configuration

Key settings in `meta/services.yml` and `meta/server.yml`:

| Key | Default | Description |
|-----|---------|-------------|
| `services.oidc.enabled` | `true` | Automate Keycloak OIDC setup |
| `services.postgres.enabled` | `true` | Enable PostgreSQL for Fider |
| `services.postgres.shared` | `true` | Reuse the shared PostgreSQL provider |
| `services.fider.version` | `stable` | Docker image tag |
| `server.domains.canonical` | `fider.{{ DOMAIN_PRIMARY }}` | Public domain |
| `server.status_codes.default` | `[200, 301, 302, 405]` | Expected HTTP codes for health check (405 because Fider returns 405 on HEAD requests to `/`) |

## Further resources

- [Fider GitHub](https://github.com/getfider/fider)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
