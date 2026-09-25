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

When a user logs in via Keycloak for the first time, Fider matches their email to the existing admin user and links the OIDC provider automatically. To enable SSO, set `services.sso.enabled: true` (the default) and ensure `OIDC.CLIENT.SECRET` is configured.

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
| `services.sso.enabled` | `true` | Automate Keycloak OIDC setup |
| `services.postgres.enabled` | `true` | Enable PostgreSQL for Fider |
| `services.postgres.shared` | `true` | Reuse the shared PostgreSQL provider |
| `services.fider.version` | `stable` | Docker image tag |
| `domains.canonical` | `fider.{{ DOMAIN_PRIMARY }}` | Public domain |
| `server.status_codes.default` | `[200, 301, 302, 405]` | Expected HTTP codes for health check (405 because Fider returns 405 on HEAD requests to `/`) |

## Further resources

- [Fider GitHub](https://github.com/getfider/fider)

## Persona contract opt-outs

The shared `biber` and `administrator` persona journeys are opted out via `PERSONA_BIBER_BLOCKED` / `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`.
Fider's SSO entry is a two-step modal: the header "Sign in" button only opens the provider dialog, and a second click on "Continue with … SSO" performs the Keycloak redirect, whereas the shared helper clicks exactly once and never reaches the IdP.
Both journeys are covered end-to-end by this role's own `fider: admin sso login` and `fider: biber sso login as regular user` scenarios in `files/playwright/playwright.spec.js`; the opt-out lapses once the shared helper learns Fider's modal.
