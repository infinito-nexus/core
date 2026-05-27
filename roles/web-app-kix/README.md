# KIX

## Description

[KIX Start](https://www.kixdesk.com/) is an open-source IT service management and helpdesk platform forked from OTRS. It provides ticket management, configuration management, knowledge base, and reporting for IT service teams.

## Overview

This role deploys KIX as an Infinito.Nexus web app behind the project's standard `sys-stk-front-proxy` and `web-app-oauth2-proxy` chain. The upstream `kix-on-premise` four-container stack (proxy, backend, frontend, db) ships from `docker-registry.kixdesk.com/public/`. The bundled `db` image carries the KIX-specific PostgreSQL init schema, so the role does not consume the shared `svc-db-postgres` cluster; the backend cache reuses the shared `svc-db-redis` instance auto-wired by `sys-stk-backend` for the OAuth2-proxy session store. Initial admin credentials are seeded via `INITIAL_ADMIN_PW` on first start (see `meta/schema.yml`).

## Features

- **TLS and HSTS:** KIX is reachable at `kix.<DOMAIN_PRIMARY>` via `sys-stk-front-proxy` with HSTS enabled.
- **OAuth2 proxy gate:** Every request is gated by `web-app-oauth2-proxy` (`services.oauth2.enabled: true`). The Keycloak realm-level OTP and WebAuthn flow enforces 2FA before the OAuth2 proxy admits a session; KIX itself carries no 2FA logic.
- **Per-app RBAC:** Members of `/roles/web-app-kix/administrator` or `/roles/web-app-kix/user` are admitted to KIX; other users are blocked at the OAuth2 proxy. The `user` role is declared via `meta/rbac.yml` so non-admin agents can be granted helpdesk access without bumping them to global administrator.
- **LDAP user directory:** KIX' `Auth::LDAP` and `Auth::Sync::LDAP` modules are wired against `svc-db-openldap`, with one backend per role group. On first login KIX pulls the user's profile (display name, email, group membership) from LDAP, so no manual KIX-side user pre-creation is required.
- **Custom `kix-proxy` routing:** The role bind-mounts a complete `default.conf` into the upstream `kix-proxy` container that exposes the agent portal on port 80, routes through the frontend Node server, and forwards the OAuth2-proxy `X-Forwarded-User` header as a `Remote-User` upstream header.
- **Outbound mail:** KIX notification mail flows through the project's `sys-svc-mail-smtp` relay.
- **Dashboard card:** `web-app-dashboard` surfaces a KIX tile pointing at the canonical URL.
- **Universal logout:** The project logout endpoint terminates the KIX session alongside every other Infinito.Nexus app.

## Further Resources

- [KIX Start website](https://www.kixdesk.com/)
- [KIX documentation](https://docs.kixdesk.com/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
