# Semaphore UI

## Description

[Semaphore UI](https://semaphoreui.com/) (repo [`semaphoreui/semaphore`](https://github.com/semaphoreui/semaphore)) is a modern web UI and API for running Ansible playbooks, Terraform/OpenTofu plans, and shell scripts on a schedule or on demand. This role deploys Semaphore behind the Infinito.Nexus reverse proxy with central PostgreSQL, native Keycloak OIDC Single Sign-On, and optional LDAP login.

## Overview

The role deploys the single official `semaphoreui/semaphore` container (with its embedded task runner) and wires it into the platform via `SEMAPHORE_*` environment variables. The setup wizard is bypassed by seeding the initial admin from rendered secrets, so a fresh deploy lands directly on the Semaphore login page.

## Features

- **Central PostgreSQL** — `SEMAPHORE_DB_DIALECT=postgres` against the shared `svc-db-postgres` (or a per-role engine when not shared), with centralised backup and monitoring.
- **Native OIDC SSO** — Semaphore renders its own "Sign in with Keycloak" button via `SEMAPHORE_OIDC_PROVIDERS`; the Keycloak client is auto-provisioned by `web-app-keycloak` (the role's canonical domain is auto-added to the shared client's redirect URIs).
- **LDAP login** — when `svc-db-openldap` is present, Semaphore's login form binds against the central OpenLDAP directory (`SEMAPHORE_LDAP_*`).
- **Always-on break-glass admin** — `SEMAPHORE_ADMIN*` seeds a local admin in every variant; it is the fallback when SSO/LDAP are unavailable.
- **Embedded runner** — automation executes inside the main container; external runner agents are a future enhancement.

## Authentication & admin model

Semaphore's auth has hard constraints (verified against the upstream `v2.18.12` source):

- The login **form** authenticates against the local user DB when LDAP is off, but switches to **LDAP-only** when `ldap_enable=true` — there is no local-password fallback.
- The **OIDC** callback matches users **by email**, *rejects* a match that is a local (non-external) account ("conflicts with local user"), and creates new OIDC users as **non-admin, external**. It never assigns admin from a claim (upstream has no claim→role mapping yet).

The role works with these constraints rather than against them:

- **Break-glass local admin** — always seeded via `SEMAPHORE_ADMIN*` with a dedicated login (`breakglass`) and dedicated email (`breakglass@<DOMAIN_PRIMARY>`) so it never collides with the SSO/LDAP identities. Reachable through the form **only when LDAP is disabled**, where it is the sole admin.
- **OIDC admin** — when SSO is enabled the role creates the Keycloak `administrator` (matching `preferred_username` + email) as an **external admin** at deploy time via `semaphore user add --admin --external`. The OIDC callback then matches that external account by email and signs the operator straight in as a Semaphore admin — no manual promotion, no claim mapping needed.
- **Regular SSO/LDAP users** (e.g. `biber`) are created as non-admin members on first sign-in.

| Variant | Admin login | Member login |
| --- | --- | --- |
| V1 (sso+ldap) | Keycloak `administrator` via OIDC (external admin) | `biber` via OIDC or LDAP |
| V2 (no auth) | `breakglass` via the local form | — |
| V3 (ldap only) | — (LDAP users are non-admin; promote manually if needed) | `biber` via LDAP |

## Variant matrix

| Variant | `sso` | `ldap` | Notes |
| --- | --- | --- | --- |
| V1 | on | on | OIDC is the primary login button; LDAP and the break-glass admin also work. |
| V2 | off | off | Local admin only. |
| V3 | off | on | LDAP login + break-glass admin. |

## Image & bump policy

Pinned to a concrete stable `2.x` tag in [`meta/services.yml`](./meta/services.yml) (`semaphoreui/semaphore:v2.18.12`); never `:latest`. Bump by editing that tag after reviewing the upstream [releases](https://github.com/semaphoreui/semaphore/releases).

## Further Resources

- [Semaphore UI Official Website](https://semaphoreui.com/)
- [Semaphore Documentation](https://docs.semaphoreui.com/)
- [OIDC / Keycloak configuration](https://docs.semaphoreui.com/administration-guide/openid/keycloak/)
- [Semaphore GitHub Repository](https://github.com/semaphoreui/semaphore)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
