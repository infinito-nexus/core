# Zammad

## Description

[Zammad](https://zammad.org/) is an open-source helpdesk and ticketing system. Agents handle customer requests across email, chat, phone and web; customers can open tickets from a self-service portal.

## Overview

This role deploys Zammad as an Infinito.Nexus web app using the upstream `ghcr.io/zammad/zammad` image (Rails app, WebSocket, scheduler, nginx, plus a one-shot init container that bypasses the setup wizard via `auto_wizard.json`). Search is provided by a bundled Elasticsearch container; PostgreSQL, Redis and Memcached are consumed from the central `svc-db-*` providers via `sys-stk-full`. Authentication uses direct OpenID Connect against the shared Keycloak client; LDAP federation and SMTP/IMAP via Mailu are wired when their providers are present.

## Features

- **Helpdesk ticketing:** Multi-channel agent and customer surface for email, web and (optionally) chat tickets.
- **Direct OIDC SSO:** Sign in through the shared Keycloak OIDC client without an oauth2-proxy sidecar; redirect URI is auto-registered.
- **LDAP federation:** When `svc-db-openldap` is present, Zammad authenticates and provisions accounts against the central LDAP.
- **Mail-to-ticket:** When `web-app-mailu` is present, the `helpdesk` mailbox is auto-provisioned and Zammad polls it to create tickets from incoming mail.
- **Server-name alias:** `zammad.helpdesk.{{ DOMAIN_PRIMARY }}` is a true vhost alias of `helpdesk.{{ DOMAIN_PRIMARY }}` (not a 301 redirect).
- **Bundled Elasticsearch:** Search engine ships with the role until a central `svc-db-elasticsearch` exists.
- **Wizard bypass:** First deploy seeds `auto_wizard.json` so no manual setup UI step is required.

## Developer Notes

Variant matrix lives in [variants.yml](./meta/variants.yml). Service flags and image pins in [services.yml](./meta/services.yml). Credentials declared in [schema.yml](./meta/schema.yml). Follow-up work tracked in [TODO.md](./TODO.md).

## Further Resources

- [Zammad Official Website](https://zammad.org/)
- [Zammad Docker Compose Documentation](https://docs.zammad.org/en/latest/install/docker-compose.html)
- [Zammad GitHub](https://github.com/zammad/zammad)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
