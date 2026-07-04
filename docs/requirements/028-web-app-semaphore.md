# 028 - Semaphore UI Role with OIDC SSO + LDAP

## User Story

As a platform administrator of Infinito.Nexus, I want [Semaphore UI](https://github.com/semaphoreui/semaphore) integrated as a `web-app-semaphore` role with OpenID Connect (Keycloak) SSO and optional LDAP login so that operators can run Ansible / Terraform / OpenTofu / Bash automation from a web UI behind the platform's central Single Sign-On, reusing the central database, and validated end-to-end with Playwright personas.

## Background

[Semaphore UI](https://semaphoreui.com/) (formerly *Ansible Semaphore*, repo `semaphoreui/semaphore`) is an open-source, Go-based web UI and API for running Ansible playbooks, Terraform/OpenTofu plans, and shell scripts on a schedule or on demand. It ships a single official container image `semaphoreui/semaphore` and is configured almost entirely through `SEMAPHORE_*` environment variables (preferred for containers) or a mounted `config.json`.

### Upstream facts established by research

| Topic | Finding | Source |
|---|---|---|
| Image | `semaphoreui/semaphore` (Docker Hub + `ghcr.io`); pin a concrete stable `2.x` semver (no `:latest`). | [Docker docs](https://docs.semaphoreui.com/administration-guide/installation/docker), [Docker Hub](https://hub.docker.com/r/semaphoreui/semaphore) |
| Config model | All settings available as `SEMAPHORE_*` env vars; `_FILE` suffix reads a value from a file (secret-friendly). | [env-vars](https://semaphoreui.com/docs/admin-guide/configuration/env-vars) |
| Database | `SEMAPHORE_DB_DIALECT` ∈ `bolt` (file at `/var/lib/semaphore`), `mysql`, `postgres`. Postgres uses `SEMAPHORE_DB_HOST/PORT/USER/PASS/SEMAPHORE_DB`. | [Configuration](https://semaphoreui.com/docs/admin-guide/configuration) |
| Admin bootstrap | `SEMAPHORE_ADMIN`, `SEMAPHORE_ADMIN_PASSWORD`, `SEMAPHORE_ADMIN_NAME`, `SEMAPHORE_ADMIN_EMAIL` seed the first admin (no setup wizard). | [Docker docs](https://docs.semaphoreui.com/administration-guide/installation/docker) |
| Secrets | `SEMAPHORE_ACCESS_KEY_ENCRYPTION` (base64 32 bytes, `head -c32 /dev/urandom \| base64`) encrypts stored access keys; `SEMAPHORE_COOKIE_HASH` / `SEMAPHORE_COOKIE_ENCRYPTION` secure sessions. | [Configuration](https://semaphoreui.com/docs/admin-guide/configuration) |
| OIDC (native) | `SEMAPHORE_OIDC_PROVIDERS` = JSON map. Per-provider: `display_name`, `provider_url` (issuer), `client_id`, `client_secret`, `redirect_url`. Redirect path is `https://<host>/api/auth/oidc/<provider_id>/redirect`. **Semaphore has native OIDC — no `oauth2-proxy` sidecar needed.** | [OpenID docs](https://docs.semaphoreui.com/administration-guide/openid/), [Keycloak config](https://docs.semaphoreui.com/administration-guide/openid/keycloak/) |
| LDAP (native) | `SEMAPHORE_LDAP_ACTIVATED`, `SEMAPHORE_LDAP_HOST`, `SEMAPHORE_LDAP_PORT`, `SEMAPHORE_LDAP_NEEDTLS`, `SEMAPHORE_LDAP_DN_BIND`, `SEMAPHORE_LDAP_PASSWORD`, `SEMAPHORE_LDAP_DN_SEARCH`, `SEMAPHORE_LDAP_SEARCH_FILTER`, plus attribute mappings (`SEMAPHORE_LDAP_MAPPING_DN/UID/MAIL/CN`). | [LDAP discussion #2106](https://github.com/semaphoreui/semaphore/discussions/2106) |
| Reverse proxy | `SEMAPHORE_WEB_ROOT` sets the externally-reachable base URL; required for correct OIDC redirects behind `sys-svc-proxy`. | [Configuration](https://semaphoreui.com/docs/admin-guide/configuration) |
| Runner | A built-in (embedded) runner executes tasks in the main container; external `semaphore runner` agents are optional for scale-out. | [Docker docs](https://docs.semaphoreui.com/administration-guide/installation/docker) |
| Auth precedence | When OIDC and/or LDAP are enabled, local password login is deprioritised; users authenticate via the configured provider(s). | [OpenID docs](https://docs.semaphoreui.com/administration-guide/openid/) |

### In-repo analogues

- SSO **flavor is `oidc` (native)**, not `oauth2-proxy` — same pattern as [`web-app-erpnext`](024-web-app-erpnext.md) and `web-app-odoo`: the app owns its "Login with Keycloak" button.
- Central database consumer + LDAP + OIDC + 3-variant matrix shape: closest structural template is [`web-app-openproject`](../../roles/web-app-openproject/) (Postgres consumer, `vars/ldap.yml`, OIDC, three personas).
- Keycloak OIDC client is **auto-provisioned** by `web-app-keycloak` for every OIDC consumer; no manual operator step.

## Confirmed Decisions

These decisions were confirmed by the operator before implementation starts and are NOT subject to re-litigation during implementation.

| # | Decision | Rationale |
|---|---|---|
| 1 | Canonical hostname `semaphore.{{ DOMAIN_PRIMARY }}` (alias-free v1). | Standard single-host convention for a new web-app role. |
| 2 | SSO flavor is **`oidc` (native)** — Semaphore renders its own "Sign in with Keycloak" button via `SEMAPHORE_OIDC_PROVIDERS`; the Keycloak client is auto-provisioned by `web-app-keycloak`. No `oauth2-proxy` sidecar. | Keeps Semaphore's API/runner token flow and its native auth UX, and lets LDAP coexist. |
| 3 | Database backend is **central PostgreSQL via `svc-db-postgres`** (`SEMAPHORE_DB_DIALECT=postgres`). When `shared=true` the role consumes the central engine; when `shared=false` `sys-svc-rdbms` templates a per-role Postgres. | Matches the platform convention used by [`web-app-openproject`](../../roles/web-app-openproject/); centralised backup + monitoring. |
| 4 | Runner topology is a **single all-in-one container** with the embedded runner. | Smallest v1 surface; matches the upstream default Docker compose. External runner agents are a follow-up. |
| 5 | Image `semaphoreui/semaphore` pinned to a concrete latest stable `2.x` semver (no `:latest`). | Standard upstream-pin policy across roles. |
| 6 | **Admin / role model = both** (operator: "admin anlegen wenn nicht oidc sonst claim mapping"), implemented within Semaphore's constraints: (a) a **break-glass local admin** is always seeded via `SEMAPHORE_ADMIN*` with a dedicated `breakglass` login + dedicated email — reachable via the form only when LDAP is off; (b) when SSO is enabled the role creates the Keycloak administrator as an **external admin** at deploy time (`semaphore user add --admin --external`), so the OIDC callback (matches by email, accepts only external users) elevates that operator to admin. Upstream has no claim→role mapping, so this deploy-time external-admin seed is the "smallest reconciliation step". | Verified against the v2.18.12 source: the login form is LDAP-only when `ldap_enable=true`, and the OIDC callback rejects local-user email matches and never sets admin from claims. |

## Target Schema

### Role layout

```
roles/web-app-semaphore/
├── README.md
├── files/
│   └── playwright/
│       ├── test-guest.js
│       ├── test-login-oidc-biber.js
│       ├── test-login-oidc-administrator.js
│       ├── test-login-ldap-biber.js
│       └── test-login-native-administrator.js
├── meta/
│   ├── main.yml
│   ├── info.yml
│   ├── server.yml
│   ├── services.yml
│   ├── schema.yml
│   ├── users.yml
│   ├── rbac.yml
│   ├── variants.yml
│   └── volumes.yml
├── tasks/
│   ├── main.yml
│   └── 01_core.yml
├── templates/
│   ├── compose.yml.j2
│   ├── env.j2
│   └── playwright.env.j2
└── vars/
    └── main.yml
```

### `meta/services.yml` excerpt (native OIDC, no oauth2-proxy)

```yaml
---
sso:
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
  flavor:  oidc
ldap:
  enabled: "{{ 'svc-db-openldap' in group_names }}"
  shared:  "{{ 'svc-db-openldap' in group_names }}"
logout:
  enabled: "{{ 'web-svc-logout' in group_names }}"
  shared:  "{{ 'web-svc-logout' in group_names }}"
dashboard:
  enabled: "{{ 'web-app-dashboard' in group_names }}"
  shared:  "{{ 'web-app-dashboard' in group_names }}"
# nocheck: playwright-service-flag — DB engine, covered by role-local integration tests
postgres:                                   # (per Q1; swap for mariadb/bolt if chosen)
  enabled: true                             # nocheck: dynamic-flag
  shared:  "{{ 'svc-db-postgres' in group_names }}"
semaphore:
  image:   semaphoreui/semaphore
  version: "X.Y.Z"                          # latest stable 2.x at PR time
  name:    semaphore
  ports:
    local:
      http: <free port>
  run_after:
    - web-app-keycloak
    - svc-db-postgres
  lifecycle: alpha
```

### `meta/variants.yml` (three variants, mirroring openproject)

V1 = `sso` + `ldap` both enabled; V2 = all dynamic flags `false`; V3 = `ldap` only.

## Acceptance Criteria

### Routing & TLS

- [ ] `semaphore.{{ DOMAIN_PRIMARY }}` resolves through `sys-svc-proxy` to the Semaphore container and `GET /` returns HTTP 200 with the Semaphore SPA shell.
- [ ] `SEMAPHORE_WEB_ROOT` is set to the canonical `https://` URL so OIDC redirect URLs resolve correctly behind the proxy.
- [ ] The role's `Content-Security-Policy` response header is emitted on the canonical front page and lists any enabled injector hosts.

### Role layout & image

- [ ] `roles/web-app-semaphore/` exists with the layout in [Target Schema](#role-layout).
- [ ] `meta/services.yml` pins `semaphoreui/semaphore` to a concrete stable `2.x` semver (no `:latest`).
- [ ] `meta/info.yml`, `server.yml`, `main.yml`, `schema.yml`, `users.yml`, `rbac.yml`, `variants.yml`, `volumes.yml` exist and pass the repo's role-meta lint.

### Database (Decision #3 — central PostgreSQL)

- [ ] `SEMAPHORE_DB_DIALECT=postgres` plus `SEMAPHORE_DB_HOST/PORT/USER/PASS/SEMAPHORE_DB` are wired; when `services.postgres.shared=true` the role consumes the central `svc-db-postgres` (no per-role engine), else `sys-svc-rdbms` templates a per-role Postgres.
- [ ] On a fresh deploy the schema is auto-migrated and the stack reaches a steady running state.

### First-admin bootstrap (Decision #6 — break-glass local admin)

- [ ] `SEMAPHORE_ADMIN`, `SEMAPHORE_ADMIN_PASSWORD`, `SEMAPHORE_ADMIN_NAME`, `SEMAPHORE_ADMIN_EMAIL` seed a break-glass local admin (dedicated `breakglass` login + dedicated email, no collision with the SSO/LDAP identities) in **every** variant; no setup wizard is presented on first load. Its form login is reachable only when LDAP is disabled (Semaphore forces LDAP-only form auth otherwise).
- [ ] `SEMAPHORE_ACCESS_KEY_ENCRYPTION` and the cookie hash/encryption secrets are generated once and persisted in the role's secret store (idempotent across redeploys).

### SSO / OIDC (Decisions #2, #6)

- [ ] When `web-app-keycloak` is in `group_names`, the Keycloak OIDC client for Semaphore is auto-provisioned with redirect URI `https://semaphore.<DOMAIN_PRIMARY>/api/auth/oidc/keycloak/redirect`.
- [ ] `SEMAPHORE_OIDC_PROVIDERS` is rendered as valid JSON (`keycloak` provider: `display_name`, `provider_url`=realm issuer, `client_id`, `client_secret`, `redirect_url`).
- [ ] When OIDC is enabled, the role creates the Keycloak `administrator` as an external Semaphore admin at deploy time (`semaphore user add --admin --external`, matching `preferred_username` + email), so the OIDC callback elevates that operator to admin (verified for the `administrator` persona). Upstream has no native claim→admin mapping; this deploy-time external-admin seed is the documented smallest reconciliation step (README).
- [ ] A Playwright OIDC flow (biber + administrator) clicks "Sign in with Keycloak", completes the Keycloak chain, and lands on an authenticated Semaphore surface (administrator persona additionally asserts the admin-only `/users` surface).

### LDAP (V3 + V1 dual)

- [ ] When `svc-db-openldap` is in `group_names`, `SEMAPHORE_LDAP_ENABLE=true` plus `SEMAPHORE_LDAP_SERVER` (host:port), `SEMAPHORE_LDAP_BIND_DN` / `_BIND_PASSWORD`, `SEMAPHORE_LDAP_SEARCH_DN` / `_SEARCH_FILTER`, and the `SEMAPHORE_LDAP_MAPPING_*` attributes are rendered from the central LDAP vars (env names per the v2.x config schema).
- [ ] An LDAP-bind login for `biber` succeeds and lands on an authenticated surface (covered by a dedicated Playwright scenario gated on `ldap`).
- [ ] When both OIDC and LDAP are enabled (V1), OIDC is the primary button and LDAP login still works; the deploy is clean.

### Variants

- [ ] `meta/variants.yml` defines exactly three variants: V1 sso+ldap, V2 all-false, V3 ldap-only.
- [ ] All three variants deploy cleanly on a fresh box (full matrix gate, all PLAY RECAPs `failed=0`).

### Playwright (per [playwright.spec.js contract](../contributing/artefact/files/role/playwright.specs.js.md))

- [ ] `files/playwright/test-guest.js`: guest never reaches an authenticated surface; empty-credentials submission is rejected by the IdP.
- [ ] `files/playwright/test-login-oidc-biber.js` and `test-login-oidc-administrator.js`: OIDC personas reach an authenticated surface, drive a role-specific interaction (e.g. open the Projects list / admin Users panel), and log out to a verified unauthenticated landing. Gated on `skipUnlessServiceEnabled('sso')`.
- [ ] `files/playwright/test-login-ldap-biber.js`: LDAP login path, gated on `skipUnlessServiceEnabled('ldap')`.
- [ ] `files/playwright/test-login-native-administrator.js`: break-glass local admin login, gated to **ldap-disabled** (Semaphore forces LDAP-only form auth when ldap is enabled); the skip carries a reason naming `LDAP_SERVICE_ENABLED`.
- [ ] `templates/playwright.env.j2` exposes every env var the specs read; service flags carry `# nocheck` rationale where applicable.
- [ ] `make compose-playwright role=web-app-semaphore` exits `0` with no stub tests and a clean logged-out final state per the contract.

### Health & quality

- [ ] The compose stack reaches a steady running state across all three variants.
- [ ] `make test` is green tree-wide (role-meta, services-contract, and playwright-parity lints pass).

### Documentation

- [ ] `roles/web-app-semaphore/README.md` documents image + bump policy, the chosen DB backend, OIDC + LDAP wiring, the variant matrix, the admin-bootstrap path, and the runner topology.
- [ ] This requirement file is cross-linked from the implementing PR (per [requirements.md#cross-linking](../contributing/requirements.md#cross-linking)).

## Validation Apps

```bash
INFINITO_APPS="web-app-semaphore" \
  make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

Smoke after deploy:

1. Visit `https://semaphore.{{ DOMAIN_PRIMARY }}/` — Semaphore login renders, no setup wizard.
2. Click "Sign in with Keycloak" — Keycloak chain completes, lands on the Semaphore dashboard.
3. (LDAP variant) Log in with an LDAP user — bind succeeds, lands authenticated.
4. Create a project / inspect the task templates UI — surface is interactive, not just reachable.

## Prerequisites

Before any implementation work, the agent MUST read [AGENTS.md](../../AGENTS.md) and follow it, then [Role Loop](../agents/action/iteration/compose.md) and the [Playwright spec contract](../contributing/artefact/files/role/playwright.specs.js.md).

## Implementation Strategy

Execute autonomously; open a clarification only when a decision is genuinely ambiguous and blocking.

1. Resolve the [Open Questions](#open-questions-pending-operator-decision) into [Confirmed Decisions](#confirmed-decisions).
2. Scaffold the role using [`roles/web-app-openproject/`](../../roles/web-app-openproject/) as the structural template (Postgres consumer, LDAP vars, OIDC, three personas).
3. Template `compose.yml.j2` + `env.j2` with the `SEMAPHORE_*` matrix (DB, admin bootstrap, secrets, `SEMAPHORE_WEB_ROOT`, conditional `SEMAPHORE_OIDC_PROVIDERS` and `SEMAPHORE_LDAP_*`).
4. Add Keycloak client auto-provisioning for the Semaphore consumer.
5. Add the Playwright specs (guest, OIDC biber+admin, LDAP biber, native admin).
6. Iterate `make test` until green, then run the Validation deploys across all three variants.

## Commit Policy

- No git commit until every Acceptance Criterion is checked off (`- [x]`).
- A single commit (or a tight related sequence) lands the whole role addition.
- When all ACs are met and the variants deploy cleanly, instruct the operator to run `git-sign-push` outside the sandbox (per [CLAUDE.md](../../CLAUDE.md)). The agent MUST NOT push.

## Context

- Upstream repo: <https://github.com/semaphoreui/semaphore>
- Upstream docs: <https://docs.semaphoreui.com/>
- OIDC / Keycloak: <https://docs.semaphoreui.com/administration-guide/openid/keycloak/>
- LDAP: <https://github.com/semaphoreui/semaphore/discussions/2106>
- Closest in-repo layout analogue: [`roles/web-app-openproject/`](../../roles/web-app-openproject/)
- Native-OIDC flavor precedent: [024 ERPNext](024-web-app-erpnext.md)
- Requirements format: [docs/contributing/requirements.md](../contributing/requirements.md)
- Playwright contract: [playwright.specs.js.md](../contributing/artefact/files/role/playwright.specs.js.md)
</content>

</invoke>
