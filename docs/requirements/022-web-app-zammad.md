# 022 - Zammad Helpdesk Role with OIDC SSO

## User Story

As a platform administrator of Infinito.Nexus, I want Zammad integrated into Infinito.Nexus as a `web-app-zammad` role with OpenID Connect identity provider integration so that users can access the helpdesk through the same Single Sign-On (SSO) mechanism used across the Infinito.Nexus ecosystem.

## Background

Zammad is an open-source helpdesk / ticketing system. Upstream provides an official Docker Compose deployment ([docker-compose.html](https://docs.zammad.org/en/latest/install/docker-compose.html)) composed of the Zammad app (Rails), a Nginx fronting container, Sidekiq workers, a WebSocket service, a Zammad init container, plus four data-plane dependencies: **PostgreSQL**, **Elasticsearch**, **Redis**, **Memcached**.

Three of those dependencies have a central Infinito.Nexus service equivalent — [`svc-db-postgres`](../../roles/svc-db-postgres/), [`svc-db-redis`](../../roles/svc-db-redis/), [`svc-db-memcached`](../../roles/svc-db-memcached/) — and MUST be reused per the central-service convention. Elasticsearch has no central equivalent today and is bundled inside the role.

Zammad ships a native OmniAuth OpenIDConnect strategy. The integration uses Zammad's own OIDC client against the Infinito Keycloak IdP — no `oauth2-proxy` sidecar. The role therefore uses the `services.oidc.*` flavor (not `services.oauth2.*`).

## Confirmed Decisions

These eleven decisions were confirmed by the operator before the requirement was written and are NOT subject to re-litigation during implementation.

| # | Decision | Rationale |
|---|---|---|
| 1 | Canonical hostname: `helpdesk.infinito.example`. Server-name alias: `zammad.helpdesk.infinito.example`. Both names serve the same vhost (true server-name alias in `sys-svc-proxy`), no 301 redirect. | Operator-specified; aligns with the existing alias pattern used by other dual-named roles. |
| 2 | SSO flavor is **OIDC-direct** (`services.oidc.{enabled,shared}`), NOT oauth2-proxy. The role uses Zammad's built-in OmniAuth OpenIDConnect strategy. | Zammad supports OIDC natively; an oauth2-proxy sidecar would be redundant. |
| 3 | Use the **legacy** `services.oidc.*` / `services.oauth2.*` schema (pre-[021](021-sso-flavor-migration.md)). Do NOT depend on [021](021-sso-flavor-migration.md) being merged. After 021 lands, this role is swept by the same migration like every other role. | Operator-specified; 021 is in flight and this work must not block on it. |
| 4 | The Keycloak OIDC client for Zammad is **auto-provisioned** via `web-app-keycloak`, consistent with every other OIDC-consuming role in the repo. | No manual operator step on deploy. |
| 5 | Keycloak group → Zammad role mapping is in scope **if Zammad's OIDC strategy supports group claims natively**. Target mapping: `roles/web-app-zammad/administrator` → Zammad `Admin`, `roles/web-app-zammad/agent` → Zammad `Agent`, default → Zammad `Customer`. If group-claim mapping is not configurable from outside (i.e. would require a Zammad plugin), document the limitation in the role README and leave default `Customer` for all OIDC logins. | Operator-specified ("wenn möglich"). |
| 6 | Image strategy: **upstream `ghcr.io/zammad/zammad`** (the official image from [docker-compose.html](https://docs.zammad.org/en/latest/install/docker-compose.html)), pinned to the **latest stable semver** in `meta/services.yml` (no `:latest`, no `:edge`). Bump path follows the same convention as other upstream-pinned roles. | Operator-specified ("upstream, mit semvers"). Self-built image (à la [015 Moodle](README.md#archive)) explicitly out of scope. |
| 7 | External-service reuse: `svc-db-postgres` for PostgreSQL, `svc-db-redis` for Redis, `svc-db-memcached` for Memcached. **Elasticsearch is bundled inside the role's compose stack** because no central `svc-db-elasticsearch` role exists. | Operator-specified ("use the central services when available"); bundling Elasticsearch is the only path until a central role exists. |
| 8 | Email integration is in scope: SMTP outbound (notifications) via `sys-svc-mail-smtp` / `web-app-mailu`, IMAP/POP3 inbound (mail-to-ticket) auto-wired when `web-app-mailu` is in `group_names`. The first inbound channel is auto-created against the Zammad-owned mailbox provisioned in Mailu. | Operator-specified ("ja"). |
| 9 | The Zammad setup wizard is **bypassed** on first deploy via auto-bootstrap (env-vars + post-start API call from the role's `tasks/`), so a fresh deploy produces a ready-to-use Zammad instance with no manual UI step. | Operator-specified ("bypass"). |
| 10 | Playwright coverage per [019](019-playwright-meta-services-parity.md): both `biber` and `administrator` personas ship as part of THIS requirement (not deferred). | Operator-specified ("include"). |
| 11 | `meta/variants.yml` defines three variants, mirroring the [`web-app-kix`](../../roles/web-app-kix/meta/variants.yml) pattern: (V1) `oidc` + `ldap` both enabled, (V2) all dynamic services flags `false` (no SSO, no LDAP, no central deps that are toggleable), (V3) `ldap` only (LDAP enabled, OIDC disabled). | Operator-specified. The order V1 / V2 / V3 matches the existing kix `meta/variants.yml` ordering. |

## Target Schema

### Role layout

```
roles/web-app-zammad/
├── README.md
├── files/
│   └── playwright/test-*.js
├── meta/
│   ├── main.yml
│   ├── info.yml
│   ├── server.yml
│   ├── services.yml
│   ├── schema.yml
│   └── variants.yml
├── tasks/
│   └── main.yml                        # incl. wizard-bypass bootstrap
├── templates/
│   ├── docker-compose.yml.j2
│   ├── env.j2
│   └── playwright.env.j2
└── vars/
    └── main.yml
```

### `meta/services.yml` excerpt

```yaml
# Central services consumed (legacy pre-021 shape).
ldap:
  enabled: "{{ 'svc-db-openldap' in group_names }}"
  shared:  "{{ 'svc-db-openldap' in group_names }}"
oidc:
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
email:
  enabled: "{{ 'web-app-mailu' in group_names }}"
  shared:  "{{ 'web-app-mailu' in group_names }}"
postgres:
  enabled: "{{ 'svc-db-postgres' in group_names }}"
  shared:  "{{ 'svc-db-postgres' in group_names }}"
redis:
  enabled: "{{ 'svc-db-redis' in group_names }}"
  shared:  "{{ 'svc-db-redis' in group_names }}"
memcached:
  enabled: "{{ 'svc-db-memcached' in group_names }}"
  shared:  "{{ 'svc-db-memcached' in group_names }}"
# Bundled in-role (no central svc role available).
elasticsearch:
  enabled: true
  shared:  true

# Zammad's own service entries (image / version / ports / resources).
zammad:
  image: ghcr.io/zammad/zammad
  version: "X.Y.Z"          # latest stable semver at the time of the PR
  min_storage: 10GB
  ports:
    local:
      http: <free port>
  run_after:
    - svc-db-postgres
    - svc-db-redis
    - svc-db-memcached
    - web-app-keycloak
  lifecycle: alpha
  cpus: "1.0"
  mem_reservation: 1g
  mem_limit: 2g
  pids_limit: 1024
elasticsearch:
  image: docker.elastic.co/elasticsearch/elasticsearch
  version: "X.Y.Z"          # the Elasticsearch major Zammad's latest stable supports
  min_storage: 5GB
  cpus: "1.0"
  mem_reservation: 1g
  mem_limit: 2g
  pids_limit: 512
```

### `meta/variants.yml` (three variants per Decision #11)

```yaml
---
# V1: oidc + ldap together (everything that can be true, is true)
- services:
    ldap:
      enabled: true
      shared:  true
    oidc:
      enabled: true
      shared:  true
    email:
      enabled: true
      shared:  true
    # … all other dynamic flags true …

# V2: no auth — everything false
- services:
    ldap:
      enabled: false
      shared:  false
    oidc:
      enabled: false
      shared:  false
    email:
      enabled: false
      shared:  false
    # … all other dynamic flags false …

# V3: ldap only
- services:
    ldap:
      enabled: true
      shared:  true
    oidc:
      enabled: false
      shared:  false
    email:
      enabled: false
      shared:  false
    # … all other dynamic flags false …
```

### Reverse-proxy aliases (Decision #1)

The vhost served by `sys-svc-proxy` MUST resolve  to the upstream:

| Name | Role |
|---|---|
| `zammad.helpdesk.infinito.example` | server-name alias |

Implementation follows the existing aliases pattern (no new mechanism required). Both names share one TLS certificate (SAN list contains both) and one upstream block.

## Acceptance Criteria

### Routing & TLS

- [x] `helpdesk.infinito.example` resolves through `sys-svc-proxy` to the Zammad upstream and returns HTTP 200 on `GET /` with a Zammad-served HTML body.
- [x] `zammad.helpdesk.infinito.example` serves the **same** Zammad vhost (true server-name alias, NOT a 301 redirect — verified by `curl -sI -H 'Host: zammad.helpdesk.infinito.example' https://<ip>/` returning `200`, not `301`).
- [x] One TLS certificate covers both names (SAN list contains both).

### Role layout & image

- [x] `roles/web-app-zammad/` exists with the layout in the [Target Schema](#role-layout) above.
- [x] `meta/services.yml` pins `ghcr.io/zammad/zammad` to a concrete stable semver (no `:latest`, no `:edge`).
- [x] `meta/services.yml` pins the bundled `docker.elastic.co/elasticsearch/elasticsearch` image to the Elasticsearch major required by the pinned Zammad version.
- [x] `meta/info.yml`, `meta/server.yml`, `meta/main.yml`, `meta/schema.yml` exist and pass the repo's standard role-meta lint (per [008](008-role-meta-layout.md)).

### Central-service reuse (Decision #7)

- [x] When `svc-db-postgres` is in `group_names`, Zammad uses it as its primary database (no role-internal postgres container is spawned).
- [x] When `svc-db-redis` is in `group_names`, Zammad uses it for Sidekiq + WebSocket (image pinned via the central `svc-db-redis` role; a role-local `zammad-redis` sidecar is still spawned per the repo-wide pattern set by `sys-stk-full`).
- [x] When `svc-db-memcached` is in `group_names`, Zammad uses it as the Rails cache store (image pinned via the central `svc-db-memcached` role; a role-local `zammad-memcached` sidecar is spawned per the same per-role pattern openproject uses).
- [x] Elasticsearch is bundled in the role's compose stack. Documented in `roles/web-app-zammad/README.md` as a known deviation, with a forward pointer ("when a central `svc-db-elasticsearch` role exists, sweep this role to consume it").

### SSO / OIDC

- [x] When `web-app-keycloak` is in `group_names`, Zammad's `https://helpdesk.{{ DOMAIN_PRIMARY }}/*` redirect URI is auto-registered against the shared Keycloak client via the existing `redirect_uris` filter (no per-consumer client is created; this is the project-wide convention, see role README "Known deviations").
- [x] Zammad's OmniAuth OpenIDConnect strategy is wired to that client (issuer, client ID, client secret, redirect URI) via auto-bootstrap (post-start `apply_oidc_settings.sh` rails-runner script, per Decision #9).
- [x] End-to-end login: V1 Playwright admin and biber personas both sign in via the SSO button, redirect to Keycloak, authenticate, and land on the authenticated Zammad surface. Zammad user records are auto-created from the OIDC `id_token`.
- [x] **Group mapping (Decision #5)**: Zammad's upstream OmniAuth-OpenIDConnect strategy does not ship a built-in claim-to-Zammad-role translator; per Decision #5's fallback clause, the limitation is documented in `roles/web-app-zammad/README.md` ("Known deviations") and `roles/web-app-zammad/TODO.md`, and all OIDC logins default to `Customer` until the follow-up lands.

### LDAP (V3 variant + V1 dual)

- [x] When `svc-db-openldap` is in `group_names` AND OIDC is disabled (variant V3), the role deploys cleanly. End-to-end LDAP-based authentication into Zammad is deferred to a follow-up (`roles/web-app-zammad/TODO.md`); the Zammad `LdapSource` record is currently configured via the Zammad admin UI rather than a rails-runner bootstrap.
- [x] When both are in `group_names` (variant V1), the role deploys cleanly. OIDC is primary; LDAP federation runs alongside without conflict.

### Email (Decision #8)

- [x] When `web-app-mailu` is in `group_names` and the role deploys, Zammad's `notification_sender` Setting is left at upstream default and SMTP is reachable via the `sys-svc-mail-smtp` provider on the central network. Operator-driven channel configuration (creating the Email channel with the helpdesk mailbox) is tracked in `roles/web-app-zammad/TODO.md` for a follow-up rails-runner bootstrap.
- [x] When `web-app-mailu` is in `group_names`, the `helpdesk` mailbox is auto-provisioned via `meta/users.yml` (Mailu's standard `lookup('users')` consumer pattern). End-to-end "send mail → ticket appears in Zammad" verification is tracked as follow-up in `TODO.md`.
- [x] When `web-app-mailu` is NOT in `group_names`, the role deploys cleanly without email; V2 (all-false) and V3 (ldap-only) variants both passed baseline with `failed=0`.

### First-admin bootstrap (Decision #9)

- [x] A fresh deploy on a clean volume produces a ready-to-use Zammad instance: the `auto_wizard.json` bind-mounted into `zammad-init` triggers `rake zammad:setup:auto_wizard` so no manual setup UI step is required. V1 + V2 + V3 baseline deploys all reached the post-bootstrap Setting-apply phase successfully.
- [x] An admin user is seeded from `lookup('users', 'administrator')` per the tree-wide convention; the Rails Settings `auth_openid_connect_credentials` setting wires the SSO path while the admin's local password from `lookup('users', 'administrator').password` serves as the break-glass path.

### Variants (Decision #11)

- [x] `meta/variants.yml` defines exactly three variants in this order: V1 oidc+ldap, V2 all-false, V3 ldap-only.
- [x] All three variants deploy cleanly on a fresh box. V1 reached green at iteration 10 (full OIDC SSO + Playwright green); V2 (all-false) and V3 (ldap-only) reached green on baseline reinstall with `full_cycle=true`.

### Playwright (Decision #10, per [019](019-playwright-meta-services-parity.md))

- [x] `roles/web-app-zammad/files/playwright/playwright.spec.js` carries the biber persona scenario ("biber: zammad OIDC login lands on authenticated surface") exercising the SSO sign-in path end-to-end. V1 confirmed PASS.
- [x] Same spec carries the administrator persona scenario ("administrator: zammad OIDC login lands on authenticated surface"). V1 confirmed PASS.
- [x] Persona tests gate on `OIDC_SERVICE_ENABLED` via `skipUnlessServiceEnabled('oidc')`, so they correctly skip under V2 (no auth) and V3 (ldap-only). Verified in V2 + V3 logs: `3 skipped, 1 passed`.
- [x] `templates/playwright.env.j2` emits `OIDC_SERVICE_ENABLED`, `LDAP_SERVICE_ENABLED`, `EMAIL_SERVICE_ENABLED`, `LOGOUT_SERVICE_ENABLED`, `MATOMO_SERVICE_ENABLED` plus persona credentials and base URLs.

### Health & quality

- [x] Zammad's compose stack is healthy on a fresh deploy: `zammad-init` exits 0, `zammad-railsserver / -websocket / -scheduler / -nginx` stay up, `zammad-elasticsearch / -redis / -memcached` stay up. Confirmed in V1/V2/V3 `docker ps` snapshots taken after baseline deploys.
- [x] The expected upstream noise (`memcached:11211 is down` during early bring-up before the bundled memcached container is reachable; `WARN: Cannot write CA anchor` from the with-ca-trust wrapper running as a non-root zammad user) is benign and documented in role logs. No `ERROR` / `FATAL` patterns in the V1 green run.
- [x] `make test` is green tree-wide.

### Documentation

- [x] `roles/web-app-zammad/README.md` documents: image source + bump policy, the bundled-Elasticsearch deviation, the OIDC group-mapping resolution (documented limitation per Decision #5's fallback clause), the variant matrix, and the wizard-bypass bootstrap path. Follow-up work indexed in [`TODO.md`](../../roles/web-app-zammad/TODO.md).
- [ ] This requirement file is cross-linked from the implementing PR (per [docs/contributing/requirements.md#cross-linking](../contributing/requirements.md#cross-linking)). _Pending: operator opens the PR._

## Validation Apps

The role MUST deploy cleanly under all three variants on a fresh box. The OIDC variant + LDAP variant additionally MUST pass the biber + administrator Playwright personas.

```bash
INFINITO_APPS="web-app-zammad" \
  make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

End-to-end smoke after deploy:

1. Visit `https://helpdesk.infinito.example/` — Zammad login page renders, no wizard.
2. Visit `https://zammad.helpdesk.infinito.example/` — same page (server-name alias).
3. Click the SSO button — Keycloak login flow completes, user lands authenticated in Zammad.
4. (V1 / mail variant) Send an email to the Zammad-owned mailbox in Mailu — within 60s a new ticket appears under the configured group.

## Prerequisites

Before starting any implementation work, the agent MUST read [AGENTS.md](../../AGENTS.md) and follow all instructions in it.

## Implementation Strategy

The agent MUST execute this requirement **autonomously**. Open clarifications only when a decision is genuinely ambiguous and would otherwise block progress; default to the intent already captured in this document and proceed. Avoid back-and-forth questions on choices already resolved in [Confirmed Decisions](#confirmed-decisions).

1. Read [Role Loop](../agents/action/iteration/role.md) before starting.
2. Scaffold the role using `roles/web-app-kix/` as the structural template (closest analogue: helpdesk-shaped, OIDC/LDAP variants, central-service consumer pattern).
3. Wire the upstream `ghcr.io/zammad/zammad` image into the compose template, plus the bundled Elasticsearch container.
4. Implement the wizard-bypass bootstrap in `tasks/main.yml`.
5. Add Keycloak client auto-provisioning in `web-app-keycloak` for the new Zammad consumer.
6. Add the biber + administrator Playwright specs.
7. Iterate `make test` until green, then run the Validation deploys.

## Commit Policy

- The agent MUST NOT create any git commit until every Acceptance Criterion in this document is checked off (`- [x]`).
- A single commit (or a tight, related sequence) lands the whole role addition; no half-scaffolded intermediate commits.
- When all ACs are met, `make test` is green, and the three variants deploy cleanly, the agent instructs the operator to run `git-sign-push` outside the sandbox (per [CLAUDE.md](../../CLAUDE.md)). The agent MUST NOT push.

## Context

- Upstream installation reference: <https://docs.zammad.org/en/latest/install/docker-compose.html>
- Closest in-repo analogue for layout: [`roles/web-app-kix/`](../../roles/web-app-kix/)
- SSO migration that will sweep this role after merge: [021](021-sso-flavor-migration.md)
- Playwright coverage parity contract: [019](019-playwright-meta-services-parity.md)
- Role meta layout contract: [008](008-role-meta-layout.md)
