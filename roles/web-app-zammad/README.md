# Zammad

## Description

[Zammad](https://zammad.org/) is an open-source helpdesk and ticketing system. Agents handle customer requests across email, chat, phone and web; customers can open tickets from a self-service portal.

## Overview

This role deploys Zammad as an Infinito.Nexus web app using the upstream `ghcr.io/zammad/zammad` image (Rails app, WebSocket, scheduler, nginx, plus a one-shot init container that bypasses the setup wizard via `auto_wizard.json`). Search is provided by a bundled Elasticsearch container; PostgreSQL, Redis and Memcached are consumed from the central `svc-db-*` providers via `sys-stk-full`. Authentication uses direct OpenID Connect against the shared Keycloak client; LDAP federation and SMTP/IMAP via Stalwart are wired when their providers are present.

## Features

- **Helpdesk ticketing:** Multi-channel agent and customer surface for email, web and (optionally) chat tickets.
- **Direct OIDC SSO:** Sign in through the shared Keycloak OIDC client without an oauth2-proxy sidecar; redirect URI is auto-registered.
- **LDAP federation:** When `svc-db-openldap` is present, Zammad authenticates and provisions accounts against the central LDAP.
- **Mail-to-ticket:** When `web-app-stalwart` is present, the `helpdesk` mailbox is auto-provisioned and Zammad polls it to create tickets from incoming mail.
- **Server-name alias:** `zammad.helpdesk.{{ DOMAIN_PRIMARY }}` is a true vhost alias of `helpdesk.{{ DOMAIN_PRIMARY }}` (not a 301 redirect).
- **Bundled Elasticsearch:** Search engine ships with the role until a central `svc-db-elasticsearch` exists.
- **Search index per Elasticsearch major:** The index lives in a directory named after the Elasticsearch major inside the `zammad_search` volume. A new major starts on an empty directory and `zammad-init` rebuilds the index from the database on the same deploy.
- **Wizard bypass:** First deploy seeds `auto_wizard.json` so no manual setup UI step is required.

## Addons

Zammad's cross-role integrations are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `openid_connect` | `module` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `email_channel` | `bridge` | enabled whenever the `email` service is present (`web-app-mailu` co-deployed) | `email` → `web-app-mailu` |

Both units ship with the Zammad image. [`tasks/01_manager_ops.yml`](./tasks/01_manager_ops.yml) applies [`files/ruby/apply/oidc_settings.rb`](./files/ruby/apply/oidc_settings.rb) and [`files/ruby/apply/email_channel.rb`](./files/ruby/apply/email_channel.rb) under the same service flags the addons declare, so each addon's `enabled` is a declaration of what that provisioning already gates on. Coupling is asserted by [files/playwright/addons/openid_connect.spec.js](./files/playwright/addons/openid_connect.spec.js) and [files/playwright/addons/email_channel.spec.js](./files/playwright/addons/email_channel.spec.js).

## Developer Notes

Variant matrix lives in [variants.yml](./meta/variants.yml). Service flags and image pins in [services.yml](./meta/services.yml). Credentials declared in [secrets.yml](./meta/secrets.yml).

## Further Resources

- [Zammad Official Website](https://zammad.org/)
- [Zammad Docker Compose Documentation](https://docs.zammad.org/en/latest/install/docker-compose.html)
- [Zammad GitHub](https://github.com/zammad/zammad)
