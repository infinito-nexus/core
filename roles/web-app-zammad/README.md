# Zammad

## Description

[Zammad](https://zammad.org/) is an open-source helpdesk and ticketing system. Agents handle customer requests across email, chat, phone and web; customers can open tickets from a self-service portal.

## Overview

This role deploys Zammad as an Infinito.Nexus web app using the upstream `ghcr.io/zammad/zammad` image (Rails app, WebSocket, scheduler, nginx, plus a one-shot init container that bypasses the setup wizard via `auto_wizard.json`). Search is provided by a bundled Elasticsearch container; PostgreSQL, Redis and Memcached are consumed from the central `svc-db-*` providers via `sys-stk-full`. Authentication uses direct OpenID Connect against the shared Keycloak client; LDAP federation and SMTP/IMAP via Stalwart are wired when their providers are present.

## Features

- **Helpdesk ticketing:** Multi-channel agent and customer surface for email, web and (optionally) chat tickets.
- **Direct OIDC SSO:** Sign in through the shared Keycloak OIDC client without an oauth2-proxy sidecar; redirect URI is auto-registered.
- **Keycloak owns the Zammad roles:** every OIDC sign-in rewrites the account's roles from its RBAC group membership, as declared by `ZAMMAD_OIDC_ROLE_GRANTS` in [vars/main.yml](./vars/main.yml): `administrator` grants `Admin` and `Agent`, `agent` grants `Agent`, `customer` grants `Customer`, and a sign-in whose groups match none of them grants `Customer`. A role handed out by hand in the Zammad admin panel is therefore replaced at the account's next sign-in. The roles are left untouched, with an error in the Rails log, whenever the mapping cannot be applied: no group claim in the response at all, a granted role that Zammad does not have or has deactivated, or a role write Zammad's own guards refuse (the last admin, the agent limit). The native `Admin` + `Agent` account of [files/ruby/apply/administrator.rb](./files/ruby/apply/administrator.rb) is only converged while `sso` is off, and the OIDC path grants roles only, not the `Users` group access that script also sets.
- **LDAP federation:** When `svc-db-openldap` is present, Zammad authenticates and provisions accounts against the central LDAP.
- **Mail-to-ticket:** When `web-app-stalwart` is present, the `helpdesk` mailbox is auto-provisioned and Zammad polls it to create tickets from incoming mail.
- **Server-name alias:** `zammad.helpdesk.{{ DOMAIN_PRIMARY }}` is a true vhost alias of `helpdesk.{{ DOMAIN_PRIMARY }}` (not a 301 redirect).
- **Bundled Elasticsearch:** Search engine ships with the role until a central `svc-db-elasticsearch` exists. Its disk watermarks follow the disk size (85 / 90 / 95 % used, requiring at most 200 / 150 / 100 GB free, `services.search.watermark`); the CI and development variants lower those caps to 10 / 5 / 2 GB.
- **Search allocation precheck:** [search_allocation_precheck.sh](files/shell/search_allocation_precheck.sh) creates a one-shard probe index named after the container and fails with the answer of `_cluster/allocation/explain`, which names the disk watermark when the data disk is too full, unless Elasticsearch allocates it. `init` runs it in front of `zammad-init`. In compose, the one-shot `precheck` service runs it first and `init` depends on that service, so `compose up` stops on a refusal. Swarm renders no `precheck` service, because `depends_on` does not gate `init` there. Instead the deploy waits until the newest `init` task is `Complete`: a refusing Elasticsearch leaves it `Failed`, the wait stops the deploy, and `docker service logs` of `init` carries the explanation. An `init` the stack deploy did not restart is already `Complete` and passes at once.
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
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/U7WFLVC7Qut2pnjLDEzGUr)
