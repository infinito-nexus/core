# Zammad

## Description

[Zammad](https://zammad.org/) is an open-source helpdesk and ticketing system. Agents handle customer requests across email, chat, phone and web; customers can open tickets from a self-service portal.

## Overview

This role deploys Zammad as an Infinito.Nexus web app using the upstream `ghcr.io/zammad/zammad` image (Rails app, WebSocket, scheduler, nginx, plus a one-shot init container that bypasses the setup wizard via `auto_wizard.json`). Search is provided by a bundled Elasticsearch container; PostgreSQL, Redis and Memcached are consumed from the central `svc-db-*` providers via [svc-stack](../svc-stack/README.md). Authentication uses direct OpenID Connect against the shared Keycloak client; LDAP federation and SMTP/IMAP via the mail server ([web-app-email](../web-app-email/)) are wired when their providers are present.

## Features

- **Helpdesk ticketing:** Multi-channel agent and customer surface for email, web and (optionally) chat tickets.
- **Direct OIDC SSO:** Sign in through the shared Keycloak OIDC client without an oauth2-proxy sidecar; redirect URI is auto-registered.
- **Keycloak owns the Zammad roles:** every OIDC sign-in rewrites the account's roles from its RBAC group membership, as declared by `ZAMMAD_RBAC_ROLE_GRANTS` in [vars/main.yml](./vars/main.yml): `administrator` grants `Admin` and `Agent`, `agent` grants `Agent`, `customer` grants `Customer`, and a sign-in whose groups match none of them grants `Customer`. A role handed out by hand in the Zammad admin panel is therefore replaced at the account's next sign-in. The roles are left untouched, with an error in the Rails log, whenever the mapping cannot be applied: no group claim in the response at all, a granted role that Zammad does not have or has deactivated, or a role write Zammad's own guards refuse (the last admin, the agent limit). The native `Admin` + `Agent` account of [files/ruby/apply/administrator.rb](./files/ruby/apply/administrator.rb) is only converged while `sso` is off, and the OIDC path grants roles only, not the `Users` group access that script also sets.
- **OIDC profile sync:** Zammad requests the `phone` and `address` scopes (`ZAMMAD_OIDC_SCOPE`), and every OIDC sign-in copies the first name, last name, email, phone, street, postal code, city and country from the claims it carries onto the account (`ZAMMAD_OIDC_PROFILE_CLAIMS`, `ZAMMAD_OIDC_ADDRESS_FIELDS`). A claim the sign-in does not carry leaves the field unchanged, and an email that another Zammad account already holds is kept with an error in the Rails log.
- **LDAP federation:** When `svc-db-openldap` is present, Zammad authenticates and provisions accounts against the central LDAP.
- **LDAP role groups:** the LDAP import maps the RBAC role groups `cn=web-app-zammad-<role>` under the roles OU onto the same Zammad roles as `ZAMMAD_RBAC_ROLE_GRANTS` (`ZAMMAD_LDAP_GROUP_ROLE_MAP`). A directory user in none of them gets Zammad's signup role (`Customer`), so any directory user can open tickets. The import is the leading source for the roles of every directory user: it runs at deploy, on Zammad's own LDAP schedule and from the admin panel's LDAP integration.
- **LDAP profile fields:** the import copies the login, first name, last name, email, phone, mobile, department, street, postal code, city, country and description (into `note`) from the `LDAP.USER.ATTRIBUTES` keys (`ZAMMAD_LDAP_USER_ATTRIBUTES`). Zammad keeps street, zip, city and country as inactive user attributes, so the API returns them but the user form does not show them.
- **Mail-to-ticket:** When `web-app-email` is present, the `helpdesk` mailbox is auto-provisioned and Zammad polls it to create tickets from incoming mail.
- **Server-name alias:** `zammad.helpdesk.{{ DOMAIN_PRIMARY }}` is a true vhost alias of `helpdesk.{{ DOMAIN_PRIMARY }}` (not a 301 redirect).
- **Bundled Elasticsearch:** Search engine ships with the role until a central `svc-db-elasticsearch` exists. Its disk watermarks follow the disk size (85 / 90 / 95 % used, requiring at most 200 / 150 / 100 GB free, `services.search.watermark`); the CI and development variants lower those caps to 10 / 5 / 2 GB.
- **Search allocation precheck:** [search_allocation_precheck.sh](files/shell/search_allocation_precheck.sh) creates a one-shard probe index named after the container and fails with the answer of `_cluster/allocation/explain`, which names the disk watermark when the data disk is too full, unless Elasticsearch allocates it. `init` runs it in front of `zammad-init`. In compose, the one-shot `precheck` service runs it first and `init` depends on that service, so `compose up` stops on a refusal. Swarm renders no `precheck` service, because `depends_on` does not gate `init` there. Instead the deploy waits until the newest `init` task is `Complete`: a refusing Elasticsearch leaves it `Failed`, the wait stops the deploy, and `docker service logs` of `init` carries the explanation. An `init` the stack deploy did not restart is already `Complete` and passes at once.
- **Memory-map floor:** the bundled Elasticsearch gets `vm.max_map_count: 262144` (`ZAMMAD_SYSCTL_PARAMETERS`) through [sys-sysctl](../sys-sysctl/), persisted in `/etc/sysctl.d/99-zammad.conf`; the key is host-global, so it is skipped inside a container.
- **Search index per Elasticsearch major:** The index lives in a directory named after the Elasticsearch major inside the `zammad_search` volume. A new major starts on an empty directory and `zammad-init` rebuilds the index from the database on the same deploy.
- **Wizard bypass:** First deploy seeds `auto_wizard.json` so no manual setup UI step is required.
- **Login methods:** `services.zammad.login.method.<method>.enabled` in [meta/services.yml](./meta/services.yml) declares `sso`, `ldap`, `native`, `2fa` and `registration`, and [files/ruby/apply/login_methods.rb](./files/ruby/apply/login_methods.rb) writes them into Zammad's settings at every deploy: `sso` sets `auth_openid_connect`, `native` or `ldap` sets `user_show_password_login`, `registration` sets `user_create_account`, and `2fa` sets the authenticator app and security key methods; while it is on, `login.method.2fa.enforced` (default `true`) puts every active role into `two_factor_authentication_enforce_role_ids`, and `enforced: false` empties the list so the second factor is only offered; while `2fa` is off both methods are off, so an enforcement is dormant (`Auth::TwoFactor#user_setup_required?` starts with `enabled? &&`), and the deploy empties the list, also one an admin set, so it does not wake up once an admin enables a method again. One form serves local and LDAP accounts and Zammad cannot tell them apart, so the form is shared: with `native` off in the LDAP mode a local account still signs in through it. The LDAP import keeps running with the `ldap` service, because it carries the role mapping of the directory users. Break-glass: with the password form hidden, the sign-in page links `#admin_password_auth`, which mails an administrator a one-time password-login link; `POST /api/v1/signin` keeps accepting the local administrator accounts (the API bot of `ZAMMAD_API_BOT_USER`, the wizard administrator), as does Basic auth on the REST API.

## Addons

Zammad's cross-role integrations are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `openid_connect` | `module` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `email_channel` | `bridge` | enabled whenever the `email` service is present (`web-app-email` co-deployed) | `email` → `web-app-email` |

Both units ship with the Zammad image. [`tasks/01_manager_ops.yml`](./tasks/01_manager_ops.yml) applies [`files/ruby/apply/oidc_settings.rb`](./files/ruby/apply/oidc_settings.rb) and [`files/ruby/apply/email_channel.rb`](./files/ruby/apply/email_channel.rb) under the same service flags the addons declare, so each addon's `enabled` is a declaration of what that provisioning already gates on. Coupling is asserted by [files/playwright/addons/openid_connect.spec.js](./files/playwright/addons/openid_connect.spec.js) and [files/playwright/addons/email_channel.spec.js](./files/playwright/addons/email_channel.spec.js).

## Developer Notes

Variant matrix lives in [variants.yml](./meta/variants.yml). Service flags and image pins in [services.yml](./meta/services.yml). Credentials declared in [secrets.yml](./meta/secrets.yml).

## Further Resources

- [Zammad Official Website](https://zammad.org/)
- [Zammad Docker Compose Documentation](https://docs.zammad.org/en/latest/install/docker-compose.html)
- [Zammad GitHub](https://github.com/zammad/zammad)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/U7WFLVC7Qut2pnjLDEzGUr)
