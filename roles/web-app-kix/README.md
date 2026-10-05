# KIX

## Description

[KIX Start](https://www.kixdesk.com/) is an open-source IT service management and helpdesk platform forked from OTRS. It provides ticket management, configuration management, knowledge base, and reporting for IT service teams.

## Overview

This role deploys KIX as an Infinito.Nexus web app behind the project's standard `sys-stk-front-proxy` and `web-app-keycloak`'s SSO-proxy sidecar chain. The upstream `kix-on-premise` proxy, backend, and frontend containers ship from `docker-registry.kixdesk.com/public/`. The backend initialises its schema (`scripts/database/kix-schema.xml`) against the central `svc-db-postgres` cluster, or against the embedded postgres sidecar when no central provider is in the inventory, with `pg_trgm` pre-activated via `services.postgres.extensions`; the cache is the role-local passwordless redis sidecar (the frontend ignores `REDIS_CACHE_PASSWORD`). Initial admin credentials are seeded via `INITIAL_ADMIN_PW` on first start (see `meta/secrets.yml`).

## Features

- **TLS and HSTS:** KIX is reachable at `kix.<DOMAIN_PRIMARY>` via `sys-stk-front-proxy` with HSTS enabled.
- **OAuth2 proxy gate:** Every request is gated by `web-app-keycloak`'s SSO-proxy sidecar (`services.sso.enabled: true`). The Keycloak realm-level OTP and WebAuthn flow enforces 2FA before the OAuth2 proxy admits a session; KIX itself carries no 2FA logic.
- **Per-app RBAC:** Members of `/roles/web-app-kix/administrator` or `/roles/web-app-kix/user` are admitted to KIX; other users are blocked at the OAuth2 proxy. The `user` role is declared via `meta/rbac.yml` so non-admin agents can be granted helpdesk access without bumping them to global administrator.
- **LDAP user directory:** KIX' `Auth::LDAP` and `Auth::Sync::LDAP` modules are wired against `svc-db-openldap`, with one backend per role group. On first login KIX pulls the user's profile (display name, email, group membership) from LDAP, so no manual KIX-side user pre-creation is required.
- **Custom `kix-proxy` routing:** The role bind-mounts a complete `default.conf` into the upstream `kix-proxy` container that exposes the agent portal on port 80, routes through the frontend Node server, and forwards the OAuth2-proxy `X-Forwarded-User` header as a `Remote-User` upstream header.
- **Outbound mail:** KIX notification mail flows through the project's `sys-svc-mail-smtp` relay.
- **Dashboard card:** `web-app-dashboard` surfaces a KIX tile pointing at the canonical URL.
- **Universal logout:** The project logout endpoint terminates the KIX session alongside every other Infinito.Nexus app.

## Further Resources

- [KIX Start website](https://www.kixdesk.com/)
- [KIX documentation](https://docs.kixdesk.com/)

## Persona contract opt-outs

This role declares `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2`. KIX sits behind an oauth2-proxy whose `sso.oauth2.allowed_groups` in `meta/services.yml` admits only `roles/web-app-kix/administrator` and `roles/web-app-kix/user`; biber belongs to neither, so the proxy denies him before KIX renders anything. Past the proxy KIX is a two-stage login: the SPA still presents its own agent form at `/auth` that binds against LDAP, and the shared persona helper has no second stage after the Keycloak round-trip.

The runnable journey lives in `files/playwright/test-login-biber.js`, which first grants biber the KIX user group over the Keycloak Admin API and then drives `runKixLoginLogoutFlow` through both stages to the universal logout. The path back to the generic persona is a KIX build that accepts the proxy's trusted headers instead of demanding its own login.
