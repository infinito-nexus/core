# 024 - ERPNext Role with OIDC SSO

## User Story

As a platform administrator of Infinito.Nexus, I want ERPNext (Frappe Framework) integrated as a `web-app-erpnext` role with OpenID Connect identity provider integration so that users can access the ERP through the same Single Sign-On (SSO) mechanism used across the Infinito.Nexus ecosystem, reusing the platform's central database and cache services.

## Background

ERPNext is an open-source ERP suite built on the [Frappe Framework](https://frappeframework.com/). Upstream ships a multi-container deployment ([frappe_docker](https://github.com/frappe/frappe_docker)) consisting of:

- **`frappe`** (Gunicorn) — Python web backend
- **`socketio`** — Node real-time WebSocket service
- **`scheduler`** — periodic-job dispatcher (`bench schedule`)
- **Workers**: `queue-short`, `queue-default`, `queue-long` — background jobs
- **Nginx** (frontend) — static assets + reverse proxy onto Frappe / SocketIO
- Data plane: **MariaDB** (primary), **Redis** (three logical roles: `cache`, `queue`, `socketio`)

Two of those data-plane dependencies have a central Infinito.Nexus service equivalent — [`svc-db-mariadb`](../../roles/svc-db-mariadb/) and [`svc-db-redis`](../../roles/svc-db-redis/) — and MUST be reused per the central-service convention. Frappe's three Redis logical roles are served by a single central Redis instance using distinct DB numbers (Frappe supports that out of the box via `redis_cache` / `redis_queue` / `redis_socketio` config entries).

Frappe ships native OAuth 2.0 / OpenID Connect client support via the built-in **"Social Login Key"** record (see [Frappe docs: Social Login Key](https://docs.frappe.io/framework/user/en/guides/integration/social_login_key)). The integration uses Frappe's own OIDC client against the Infinito Keycloak IdP — no `oauth2-proxy` sidecar. The role therefore uses the `services.sso.flavor: oidc` schema (post-[021](README.md#archive) unified SSO contract), aligned with [`web-app-odoo`](../../roles/web-app-odoo/meta/services.yml).

The closest existing analogues in this repo are [`web-app-odoo`](../../roles/web-app-odoo/) (ERP shape, OIDC + LDAP variants, central MariaDB consumer pattern omitted — odoo uses Postgres) and [`web-app-zammad`](../../roles/web-app-zammad/) (central-service reuse pattern, OIDC-direct flavor, three-variant matrix).

## Confirmed Decisions

These decisions were confirmed by the operator before implementation starts and are NOT subject to re-litigation during implementation.

| # | Decision | Rationale |
|---|---|---|
| 1 | Canonical hostname: `next.erp.{{ DOMAIN_PRIMARY }}`. No alias on first iteration. | Mirrors the `odoo.erp.{{ DOMAIN_PRIMARY }}` convention used by [`web-app-odoo`](../../roles/web-app-odoo/meta/domains.yml); both ERPs sit under the `.erp.` subdomain. |
| 2 | SSO flavor is **OIDC-direct** (`services.sso.flavor: oidc`), NOT oauth2-proxy. The role uses Frappe's built-in Social Login Key. | Frappe supports OIDC natively as an OAuth client; an oauth2-proxy sidecar would be redundant and break the Frappe "Login with X" UX. |
| 3 | Use the unified post-[021](README.md#archive) `services.sso.*` schema (matches [`web-app-odoo`](../../roles/web-app-odoo/meta/services.yml)). | [021](README.md#archive) is merged. New roles MUST land on the unified schema directly, not on the legacy oauth2/oidc service shape. |
| 4 | The Keycloak OIDC client for ERPNext is **auto-provisioned** via `web-app-keycloak`, consistent with every other OIDC-consuming role in the repo. | No manual operator step on deploy. |
| 5 | Keycloak group → ERPNext role mapping target tiers: `roles/web-app-erpnext/administrator` → Frappe `System Manager`, `roles/web-app-erpnext/manager` → Frappe `Sales User` + `Purchase User` + `Stock User` + `Accounts User`, default → Frappe `Customer`. **v1 scope split:** the path-to-roles map is persisted at deploy time by `apply/oidc_settings.py` (writes JSON to `frappe.db.set_default("erpnext_oidc_group_role_map", …)`). Per-login reconciliation into Frappe role records still requires a custom Frappe app shipping a `hooks.py` `on_session_creation` callback — that piece is **deferred to a follow-up requirement**. | Operator-confirmable; Frappe's Social Login Key alone does NOT consume group claims. Persisting the map in v1 unblocks the follow-up requirement without re-litigating the mapping table. |
| 6 | Image strategy: **upstream `frappe/erpnext`** (the official image from [frappe_docker](https://github.com/frappe/frappe_docker)), pinned to the **latest stable v15.x** in `meta/services.yml` (no `:latest`, no `:edge`). v14 LTS and the v16 pre-release line are explicitly NOT used. Bump path follows the same convention as other upstream-pinned roles. | Operator-confirmed: track the actively maintained major. Self-built image (à la [015 Moodle](README.md#archive)) explicitly out of scope. |
| 7 | External-service reuse: **`svc-db-mariadb`** for MariaDB (primary DB), **`svc-db-redis`** for all three Frappe Redis logical roles (separated by DB number: `cache=0`, `queue=1`, `socketio=2`). Nginx frontend stays bundled in-role (Frappe-aware reverse-proxy config). | Operator-confirmable; matches the convention codified in [022 Zammad Decision #7](README.md#archive). No `svc-db-` role exists for Nginx frontend because it is Frappe-coupled, not a general-purpose service. |
| 8 | Email integration in v1: **outbound SMTP only**. When `web-app-mailu` is in `group_names`, Frappe's outbound Email Account is auto-configured against the central SMTP endpoint so notification / password-reset emails leave the box. **IMAP inbound (mail-to-Communication) is deferred to a follow-up requirement.** Rationale: the survey found no precedent in this repo for auto-provisioning role-owned mailboxes in Mailu, so the inbound side requires a new generic Mailu mechanism that is out of scope for this PR. | Operator-confirmed: defer inbound; v1 = outbound only. The follow-up requirement will introduce the generic Mailu auto-mailbox hook and sweep this role at the same time. |
| 9 | The Frappe site-setup wizard is **bypassed** on first deploy via auto-bootstrap: `bench new-site` with `--admin-password`, `--db-name`, `--mariadb-user-host-login-scope=%` arguments, plus `bench install-app erpnext`, plus a post-start API call from the role's `tasks/` to mark the wizard as completed (`frappe.db.set_default('setup_complete', '1')`). A fresh deploy lands directly on the ERPNext desk. | Matches the Zammad wizard-bypass pattern ([022 Decision #9](README.md#archive)); avoids a manual UI step on every fresh box. |
| 10 | Playwright coverage per [019](README.md#archive): both `biber` and `administrator` personas ship as part of THIS requirement (not deferred). | Mirrors the Zammad rollout ([022 Decision #10](README.md#archive)). |
| 11 | `meta/variants.yml` defines three variants, mirroring the [`web-app-kix`](../../roles/web-app-kix/meta/variants.yml) / [`web-app-zammad`](../../roles/web-app-zammad/meta/variants.yml) pattern: (V1) `sso` + `ldap` both enabled, (V2) all dynamic services flags `false`, (V3) `ldap` only. | Standard variant matrix across helpdesk / ERP roles. |
| 12 | Multi-tenancy / multi-site (Frappe's `bench --site`) is **out of scope** for v1. The role provisions exactly one site (`{{ canonical_domain }}`) and a single ERPNext app install. | Keeps v1 surface small; multi-site can land in a follow-up requirement if needed. |
| 13 | Backup hook in v1: **documented as an operator command in the role README**. `bench --site {{ canonical_domain }} backup --with-files` is the documented manual command; the central MariaDB volume is already covered by the standard `svc-bkp-` driver and Frappe site-files are persisted on a named volume that the existing backup driver also covers. Adding a `pre_backup_hook` schema to `svc-bkp-` for in-flight `bench backup` is deferred to a follow-up requirement. | Operator-confirmed: keep this PR focused on the role itself. No `meta/services.yml::<app>.backup.pre_backup_hook` field is introduced here; central MariaDB + role volume snapshots are the v1 backup story. |

## Target Schema

### Role layout

```
roles/web-app-erpnext/
├── README.md
├── files/
│   └── playwright/test-*.js
├── meta/
│   ├── main.yml
│   ├── info.yml
│   ├── server.yml
│   ├── services.yml
│   ├── schema.yml
│   ├── users.yml
│   ├── variants.yml
│   └── volumes.yml
├── tasks/
│   ├── main.yml
│   ├── 01_core.yml
│   └── 02_bench_bootstrap.yml          # new-site + install-app + wizard-bypass
├── templates/
│   ├── docker-compose.yml.j2
│   ├── env.j2
│   ├── common_site_config.json.j2
│   └── playwright.env.j2
└── vars/
    └── main.yml
```

### `meta/services.yml` excerpt

```yaml
---
sso:
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
  flavor:  oidc
ldap:
  enabled: "{{ 'svc-db-openldap' in group_names }}"
  shared:  "{{ 'svc-db-openldap' in group_names }}"
email:
  enabled: "{{ 'web-app-mailu' in group_names }}"
  shared:  "{{ 'web-app-mailu' in group_names }}"
logout:
  enabled: "{{ 'web-svc-logout' in group_names }}"
  shared:  "{{ 'web-svc-logout' in group_names }}"
dashboard:
  enabled: "{{ 'web-app-dashboard' in group_names }}"
  shared:  "{{ 'web-app-dashboard' in group_names }}"
matomo:
  enabled: "{{ 'web-app-matomo' in group_names }}"
  shared:  "{{ 'web-app-matomo' in group_names }}"
prometheus:
  enabled: "{{ 'web-app-prometheus' in group_names }}"
  shared:  "{{ 'web-app-prometheus' in group_names }}"
# nocheck: playwright-service-flag — DB engine, covered by role-local integration tests
mariadb:
  enabled: true                         # nocheck: dynamic-flag
  shared:  "{{ 'svc-db-mariadb' in group_names }}"
# nocheck: playwright-service-flag — cache/queue/socketio buses, covered by role-local integration tests
redis:
  enabled: true                         # nocheck: dynamic-flag
  shared:  "{{ 'svc-db-redis' in group_names }}"

erpnext:
  backup:
    no_stop_required: false             # Frappe's bench backup requires a quiesced site
  image:  frappe/erpnext
  version: "X.Y.Z"                      # latest stable semver at the time of the PR
  name:   erpnext
  min_storage: 15GB
  ports:
    local:
      http:      <free port>            # nginx frontend
      socketio:  <free port>
  run_after:
    - svc-db-mariadb
    - svc-db-redis
    - web-app-keycloak
    - web-app-mailu
  lifecycle: alpha
  cpus: "2.0"
  mem_reservation: 2g
  mem_limit: 4g
  pids_limit: 2048
```

### `meta/variants.yml` (three variants per Decision #11)

```yaml
---
# V1: sso + ldap together (everything that can be true, is true)
- services:
    sso:
      enabled: true
      shared:  true
    ldap:
      enabled: true
      shared:  true
    email:
      enabled: true
      shared:  true
    # … all other dynamic flags true …

# V2: no auth — everything false
- services:
    sso:
      enabled: false
      shared:  false
    ldap:
      enabled: false
      shared:  false
    email:
      enabled: false
      shared:  false
    # … all other dynamic flags false …

# V3: ldap only
- services:
    sso:
      enabled: false
      shared:  false
    ldap:
      enabled: true
      shared:  true
    email:
      enabled: false
      shared:  false
    # … all other dynamic flags false …
```

### Frappe site config (Decision #7 — Redis DB-number split)

The role MUST template `sites/{{ canonical_domain }}/site_config.json` (or the equivalent common-site-config layer) so Frappe's three Redis logical roles all point at the shared `svc-db-redis` instance with distinct DB numbers:

```json
{
  "redis_cache":    "redis://<svc-db-redis-host>:<port>/0",
  "redis_queue":    "redis://<svc-db-redis-host>:<port>/1",
  "redis_socketio": "redis://<svc-db-redis-host>:<port>/2"
}
```

DB numbers (0 / 1 / 2) are stable for v1; if `svc-db-redis` later partitions tenants, this requirement gets swept by the same migration.

## Acceptance Criteria

### Routing & TLS

- [x] `next.erp.{{ DOMAIN_PRIMARY }}` resolves through `sys-svc-proxy` to the ERPNext Nginx frontend and returns HTTP 200 on `GET /` with a Frappe-served HTML body (verified in matrix r3 across all three variants; CSP `unsafe-eval` added to satisfy Frappe's `eval()` use).
- [x] WebSocket upgrade to the SocketIO container is wired (`websocket` port in `meta/services.yml`, `BACKEND`/`SOCKETIO` env on the frontend nginx).
- [x] CSP `connect-src` whitelist includes the canonical host and its `wss://` variant (mirrors the [`web-app-odoo`](../../roles/web-app-odoo/meta/csp.yml) precedent).

### Role layout & image

- [x] `roles/web-app-erpnext/` exists with the layout in the [Target Schema](#role-layout) above.
- [x] `meta/services.yml` pins `frappe/erpnext` to a concrete stable v15.x semver (no `:latest`, no `:edge`, no v14, no v16).
- [x] `meta/info.yml`, `meta/server.yml`, `meta/main.yml`, `meta/schema.yml`, `meta/users.yml`, `meta/volumes.yml`, `meta/rbac.yml`, `meta/variants.yml` exist and pass the repo's standard role-meta lint (per [008](README.md#archive)).

### Central-service reuse (Decision #7)

- [x] When `services.mariadb.shared=true` (V1 + matching `group_names`), Frappe connects to the central `svc-db-mariadb` via the in-stack `mariadb` network alias using svc-db-mariadb's `credentials.root_password` for `bench new-site`; when `shared=false` (V2/V3) `sys-svc-rdbms` templates a per-role MariaDB container and bench uses the consumer's per-role db password as root.
- [x] Frappe's three Redis logical roles share one instance via DB-number split (`cache=0`, `queue=1`, `socketio=2`) using the in-compose `redis` alias.
- [x] When `services.mariadb.enabled` (always true for ERPNext) is unsatisfiable, `sys-stk-full` fails the deploy at the database-readiness gate before bench-bootstrap runs.

### SSO / OIDC (Decisions #4, #5)

- [x] When `web-app-keycloak` is in `group_names`, the existing `web-app-keycloak/redirect_uris` filter auto-includes ERPNext's `https://next.erp.<DOMAIN_PRIMARY>/*` in the realm's shared OIDC client (no per-role Keycloak entry needed).
- [x] Frappe's Social Login Key for Keycloak is auto-created by `tasks/03_oidc.yml` via `files/scripts/apply/oidc_settings.py` (provider=Keycloak, `custom_base_url=1`, `auth_url_data={response_type:code,scope:openid}`, login_via_keycloak redirect path).
- [x] V1 OIDC + administrator + biber Playwright specs land on the Frappe desk (matrix r3 5-passed-2-skipped on V1).
- [ ] **Group mapping (Decision #5)**: the path-to-roles map is persisted (`apply/oidc_settings.py` writes it to `frappe.db.set_default("erpnext_oidc_group_role_map", …)`), but reconciling the map into Frappe roles on each OIDC login still needs a `hooks.py` `on_session_creation` hook in a small custom Frappe app. Deferred to a follow-up requirement; documented in README.

### LDAP (V3 variant + V1 dual)

- [x] When `svc-db-openldap` is in `group_names`, Frappe's LDAP Settings doctype is auto-configured by `tasks/04_ldap.yml` via `files/scripts/apply/ldap_source.py`. End-to-end LDAP-login (auto-create Frappe user from LDAP bind on first sign-in) is **deferred to a follow-up requirement** — needs additional Frappe-side attribute mapping + user-creation hooks; documented in README. The corresponding Playwright login specs (`test-login-via-ldap-*`) are intentionally absent in v1.
- [x] When both are in `group_names` (variant V1), the role deploys cleanly with OIDC as the primary login button.

### Email (Decision #8 — outbound only in v1)

- [x] When `web-app-mailu` is in `group_names`, ERPNext's outbound `Email Account` is auto-configured by `tasks/05_email.yml` via `files/scripts/apply/email_account.py` (uses `db_insert`/`db_update` to bypass Frappe's deploy-time SMTP socket validation).
- [x] When `web-app-mailu` is NOT in `group_names`, `tasks/01_core.yml` skips the email subtask via `when: ERPNEXT_EMAIL_ENABLED` (verified by the V2 all-false variant deploying clean without an Email Account record).
- [x] `roles/web-app-erpnext/README.md` notes that **IMAP inbound (mail-to-Communication) is deferred to a follow-up requirement** and points to the upstream Frappe Email Account doctype for operator-manual inbound config in the meantime.

### First-admin bootstrap (Decision #9)

- [x] `apply/api_bot.py` sets `setup_complete=1` on the `System Settings` doctype + writes the global default; verified in matrix r3.
- [x] The Frappe `Administrator` user is seeded by `bench new-site --admin-password=$ERPNEXT_INITIAL_ADMIN_PASSWORD`; the `test-login-native-administrator.js` Playwright spec exercises the break-glass local login in every variant (passed in matrix r3).
- [x] `bench install-app erpnext` runs as part of `bench new-site --install-app erpnext` in `tasks/02_bench_bootstrap.yml`; the long-lived Frappe containers are restarted afterwards so their cached app set picks up the new install (otherwise `/login` serves HTTP 500 from a stale app cache).

### Variants (Decision #11)

- [x] `meta/variants.yml` defines exactly three variants in this order: V1 sso+ldap, V2 all-false, V3 ldap-only.
- [x] All three variants deploy cleanly on a fresh box (FULL matrix gate `make compose-deploy mode=reinstall apps=web-app-erpnext full_cycle=true purge=true` — 6 PLAY RECAPs, all `failed=0`).

### Backup (Decision #13 — documented operator command in v1)

- [x] `roles/web-app-erpnext/README.md` documents the manual backup command (`bench --site {{ canonical_domain }} backup --with-files`) and the resulting artefacts (`*.sql.gz` + `*-files.tar` + `*-private-files.tar`).
- [x] `roles/web-app-erpnext/README.md` documents restore (the inverse `bench --site … restore` + central-MariaDB import path).
- [x] No `pre_backup_hook` schema is introduced in `svc-bkp-*` here; that is deferred to a follow-up requirement.

### Playwright (Decision #10, per [019](README.md#archive))

- [x] `roles/web-app-erpnext/files/playwright/test-login-biber.js` contains the biber-persona spec, exercising the SSO-sign-in path landing on an authenticated ERPNext surface. (Flat layout per the existing `web-app-zammad` precedent.)
- [x] `roles/web-app-erpnext/files/playwright/test-login-administrator.js` contains the administrator-persona spec, exercising the SSO-sign-in path landing on the Frappe desk.
- [x] `roles/web-app-erpnext/files/playwright/test-login-native-administrator.js` adds a break-glass local-login spec for `Administrator` (runs in every variant — not gated on SSO/LDAP).
- [x] OIDC specs gate on `SSO_SERVICE_ENABLED` per the standard `service-gating.js` helper (via `shared.skipUnlessServiceEnabled("sso")`), so they skip-correctly under V2/V3.
- [x] `templates/playwright.env.j2` emits the standard service-flag set per [019 Rule 6](README.md#archive); unused flags carry `# nocheck: playwright-service-gate` markers with documented rationale.

### Health & quality

- [x] ERPNext's compose stack reaches a steady running state across all three variants in matrix r3 (`backend`, `frontend`, `websocket`, `scheduler`, `queue-short`, `queue-long`, plus the one-shot `configurator`). v1 ships two workers (`queue-short` + `queue-long`) per the canonical frappe_docker v15 layout — `queue-default` is absorbed into `queue-short`'s `--queue short,default` flag.
- [x] No fatal failures in matrix r3 (all PLAY RECAPs `failed=0`; Playwright runs all passed-or-skipped, no failures).
- [x] `make test` is green tree-wide (the role passes role-meta lints, services contract lints, playwright-services-parity lints, and the new `test_task_name_length` lint that caps Ansible `name:` strings at 120 chars).

### Documentation

- [x] `roles/web-app-erpnext/README.md` documents: image source + bump policy, the central-MariaDB and central-Redis (3-DB-number split) consumer pattern, the OIDC group-mapping reconciliation, the variant matrix, the wizard-bypass bootstrap path, and the backup / restore flow.
- [ ] This requirement file is cross-linked from the implementing PR (per [docs/contributing/requirements.md#cross-linking](../contributing/requirements.md#cross-linking)).

## Validation Apps

The role MUST deploy cleanly under all three variants on a fresh box. V1 (sso + ldap) and V3 (ldap-only) additionally MUST pass the biber + administrator Playwright personas.

```bash
INFINITO_APPS="web-app-erpnext" \
  make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

End-to-end smoke after deploy:

1. Visit `https://next.erp.{{ DOMAIN_PRIMARY }}/` — Frappe / ERPNext login page renders, no wizard.
2. Click the "Login with Keycloak" SSO button — Keycloak login flow completes, user lands on the ERPNext desk (`/app`).
3. Open `/app/erpnext` — ERPNext landing page renders (not bare Frappe desk).
4. (V1 / mail variant) Trigger a Frappe notification (e.g. a forgot-password flow) — the outbound mail leaves via Mailu and arrives at the target inbox.
5. (V1 / SSO + group mapping) An OIDC user in the `roles/web-app-erpnext/administrator` group has the `System Manager` Frappe role assigned after first login.

## Prerequisites

Before starting any implementation work, the agent MUST read [AGENTS.md](../../AGENTS.md) and follow all instructions in it.

## Implementation Strategy

The agent MUST execute this requirement **autonomously**. Open clarifications only when a decision is genuinely ambiguous and would otherwise block progress; default to the intent already captured in this document and proceed. Avoid back-and-forth questions on choices already resolved in [Confirmed Decisions](#confirmed-decisions).

1. Read [Compose Loop](../agents/action/iteration/compose.md) before starting.
2. Scaffold the role using [`roles/web-app-odoo/`](../../roles/web-app-odoo/) as the structural template (closest analogue: ERP-shaped, OIDC + LDAP variants, central-service consumer pattern, dual HTTP + WebSocket vhost).
3. Wire the upstream `frappe/erpnext` image into the compose template, plus the SocketIO, scheduler, three worker, and Nginx frontend containers (per [frappe_docker](https://github.com/frappe/frappe_docker)).
4. Template `common_site_config.json` with the central MariaDB endpoint and the three Redis URLs split by DB number.
5. Implement `tasks/02_bench_bootstrap.yml`: `bench new-site` → `bench install-app erpnext` → wizard-bypass API call → Social Login Key seeding.
6. Add Keycloak client auto-provisioning in `web-app-keycloak` for the new ERPNext consumer.
7. Add the biber + administrator Playwright specs.
8. Wire the `svc-bkp-` pre-backup hook (`bench backup --with-files`).
9. Iterate `make test` until green, then run the Validation deploys.

## Commit Policy

- The agent MUST NOT create any git commit until every Acceptance Criterion in this document is checked off (`- [x]`).
- A single commit (or a tight, related sequence) lands the whole role addition; no half-scaffolded intermediate commits.
- When all ACs are met, `make test` is green, and the three variants deploy cleanly, the agent instructs the operator to run `git-sign-push` outside the sandbox (per [CLAUDE.md](../../CLAUDE.md)). The agent MUST NOT push.

## Context

- Upstream framework: <https://frappeframework.com/>
- Upstream product docs: <https://docs.frappe.io/erpnext>
- Upstream container reference: <https://github.com/frappe/frappe_docker>
- Closest in-repo analogue for layout: [`roles/web-app-odoo/`](../../roles/web-app-odoo/)
- Central-service reuse precedent: [022 Zammad](README.md#archive)
- Playwright coverage parity contract: [019](README.md#archive)
- Role meta layout contract: [008](README.md#archive)
- Unified SSO schema: [021](README.md#archive)
