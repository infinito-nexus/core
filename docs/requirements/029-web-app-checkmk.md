# 029 - Checkmk Role with oauth2-proxy SSO + LDAP

## User Story

As a platform administrator of Infinito.Nexus, I want [Checkmk](https://github.com/Checkmk/checkmk) integrated as a `web-app-checkmk` role with Keycloak SSO (via the oauth2-proxy gate) and native LDAP user management so that operators can run the open-source Checkmk monitoring server behind the platform's central Single Sign-On, validated end-to-end with Playwright personas.

## Background

[Checkmk](https://checkmk.com/) is an open-source IT/infrastructure & application monitoring system. The **Raw / Community** edition (100% open source) ships an official all-in-one container that bundles the monitoring core, RRD storage, and the Apache-served web GUI — it needs **no external database**.

### Upstream facts established by research

| Topic | Finding | Source |
|---|---|---|
| Image | `checkmk/check-mk-raw` (Raw/Community, free); renamed `checkmk/check-mk-community` from 2.5. Pin a concrete patch tag (no `:latest`). | [Docker Hub](https://hub.docker.com/r/checkmk/check-mk-raw/), [Docker docs](https://docs.checkmk.com/latest/en/introduction_docker.html) |
| Bootstrap env | `CMK_SITE_ID` (OMD site, default `cmk`), `CMK_PASSWORD` (initial `cmkadmin` password, **first run only**), `TZ`, `MAIL_*` for outbound mail. | [managing_docker](https://docs.checkmk.com/latest/en/managing_docker.html) |
| Ports | `5000` = site Apache (GUI at `/<site>/check_mk/`), `8000` = agent receiver (TLS agent registration). | [introduction_docker](https://docs.checkmk.com/latest/en/introduction_docker.html) |
| Database | None external — Checkmk Raw bundles Nagios core + RRDtool; all state on one persistent volume (`/omd/sites`). | [managing_docker](https://docs.checkmk.com/latest/en/managing_docker.html) |
| LDAP | **Native in all editions** (incl. Raw): LDAP "connections" sync users, contact groups, roles. | [ldap.html](https://docs.checkmk.com/latest/en/ldap.html) |
| SAML | Commercial editions only; Raw needs `mod_auth_mellon` (manual, unsupported). | [saml.html](https://docs.checkmk.com/latest/en/saml.html) |
| OIDC | **Not native in any edition**; Raw only via Apache `mod_auth_openidc` (manual PoC). → use the platform oauth2-proxy gate instead. | [Forum HOWTO](https://forum.checkmk.com/t/howto-cmk-with-oidc-authentication/37168) |
| Header SSO | Global setting **"Authenticate users by incoming HTTP requests"** / `auth_by_http_header = "X-Remote-User"` — reads the username from a trusted reverse-proxy header. | [Werk #7819](https://checkmk.com/werk/7819), [omd_https](https://docs.checkmk.com/latest/en/omd_https.html) |

### In-repo analogues

- **SSO flavor is `oauth2`** (oauth2-proxy sidecar → Keycloak), NOT native OIDC — because Checkmk Raw has no OIDC. The oauth2-proxy authenticates against Keycloak and passes `X-Remote-User`; Checkmk's site Apache trusts it via `auth_by_http_header`. This mirrors [`web-app-openproject`](../../roles/web-app-openproject/)'s header-SSO bridge (`OPENPROJECT_AUTH__SOURCE__SSO_HEADER` + LDAP-gated header trust).
- **LDAP native** (the user record + roles/contact groups), gated on `svc-db-openldap`, so the `X-Remote-User` (Keycloak `preferred_username`) resolves to a real Checkmk user.
- No external DB consumer (unlike the Semaphore role, which is tracked on a separate branch/PR).

## Confirmed Decisions

These decisions were confirmed by the operator before implementation starts and are NOT subject to re-litigation during implementation.

| # | Decision | Rationale |
|---|---|---|
| 1 | Canonical hostname `monitoring.{{ DOMAIN_PRIMARY }}`; GUI served under the site path `/<site>/check_mk/`. | Standard single-host convention; Checkmk serves its GUI under the OMD site path. |
| 2 | Edition is **Raw / Community** (`checkmk/check-mk-raw`). | Operator decision: 100% open source, matches the platform; OIDC handled via the oauth2-proxy gate. |
| 3 | SSO is the **oauth2-proxy gate + Checkmk header-auth (`auth_by_http_header = "X-Remote-User"`) + native LDAP**. | Operator decision: Keycloak SSO at the proxy, Checkmk trusts the proxy-supplied user, LDAP supplies the user record/roles/contact groups. |
| 4 | The **agent receiver (port 8000) IS exposed** (mapped + proxied) for TLS agent registration. | Operator decision: enable remote-host agent registration in v1. |
| 5 | Image pinned to a concrete stable Checkmk 2.x patch tag (no `:latest`). | Standard upstream-pin policy. |
| 6 | OMD site id `cmk`; single site; no external DB; one persistent volume for `/omd/sites`. | Checkmk Raw bundles its own core/RRD; nothing external needed. |

## Target Schema

### Role layout

```
roles/web-app-checkmk/
├── README.md
├── files/playwright/{_shared,playwright.spec,test-guest,test-login-oidc-biber,test-login-oidc-administrator,test-login-ldap-biber}.js
├── meta/{main,info,server,services,schema,users,rbac,variants,volumes}.yml
├── tasks/{main,01_core}.yml
├── templates/{compose.yml.j2,env.j2,playwright.env.j2}
└── vars/main.yml
```

### `meta/services.yml` excerpt (oauth2-proxy flavor, no external DB)

```yaml
sso:
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
  flavor:  oauth2
  oauth2:
    origin: { host: application, port: "5000" }
ldap:
  enabled: "{{ 'svc-db-openldap' in group_names }}"
  shared:  "{{ 'svc-db-openldap' in group_names }}"
checkmk:
  image:   checkmk/check-mk-raw
  version: "X.Y.Zp?"
  name:    checkmk
  ports:
    internal: { http: 5000 }
    local:    { http: <free port> }
  run_after: [web-app-keycloak]
  lifecycle: alpha
```

## Acceptance Criteria

### Routing & TLS

- [ ] `monitoring.{{ DOMAIN_PRIMARY }}` resolves through `sys-svc-proxy` (and, when SSO is on, the oauth2-proxy gate) to the Checkmk site Apache; `GET /<site>/check_mk/` returns the Checkmk login/GUI.
- [ ] The site-path redirect (`/` → `/<site>/check_mk/`) works behind the proxy.
- [ ] The role emits a `Content-Security-Policy` header on the canonical surface.
- [ ] The agent receiver (container port `8000`) is mapped to a host port (Decision #4) and reachable for TLS agent registration.

### Role layout & image

- [ ] `roles/web-app-checkmk/` exists per the [Target Schema](#role-layout); image pinned to a concrete Checkmk 2.x patch (no `:latest`).
- [ ] All `meta/*.yml` exist and pass the role-meta lint.

### Bootstrap

- [ ] `CMK_SITE_ID`, `CMK_PASSWORD` (from a rendered credential), `TZ` seed the site + `cmkadmin` on first run; the stack reaches a steady running state on one persistent volume.

### SSO / oauth2 + header auth (Decision #3)

- [ ] When SSO is enabled, the oauth2-proxy gate fronts Checkmk and authenticates against Keycloak (client auto-provisioned via the `redirect_uris` filter).
- [ ] Checkmk's `auth_by_http_header = "X-Remote-User"` is configured so the proxy-supplied user is logged in without a second login.
- [ ] A Playwright OIDC flow (biber + administrator) passes the oauth2-proxy → Keycloak chain and lands authenticated in the Checkmk GUI (administrator additionally reaches a Setup/admin-only surface).

### LDAP (Decision #3)

- [ ] When `svc-db-openldap` is in `group_names`, an LDAP connection is provisioned (`files/configure-sso.sh`) so LDAP users (matching the `X-Remote-User`) exist with roles/contact groups. LDAP is a backend identity source behind the oauth2 gate — there is no separate LDAP login surface, so it is exempted from a Playwright gate (`# nocheck: playwright-service-flag`), mirroring [`web-app-openproject`](../../roles/web-app-openproject/).

### Variants

- [ ] `meta/variants.yml` defines three variants (V1 sso+ldap, V2 all-false, V3 ldap-only); all deploy cleanly on a fresh box.

### Playwright

- [ ] Persona coverage via the shared oauth2-gate helpers (mirroring [`web-app-openproject`](../../roles/web-app-openproject/)): `test-baseline.js` (reachability + guest/biber/administrator personas), `test-oidc-login.js` (oauth2 gate + `X-Remote-User` session, gated on `sso`), `test-oidc-security.js` (forged-header bypass guard). `biber`/`administrator` are gated to SSO via `PERSONA_*_BLOCKED`. `templates/playwright.env.j2` exposes every read env var; `make compose-playwright role=web-app-checkmk` exits 0 with no stub tests and a clean logged-out final state.

### Health & quality

- [ ] Stack steady across all three variants; `make test` green tree-wide.

### Documentation

- [ ] `README.md` documents edition + bump policy, the oauth2-proxy+header-auth+LDAP model, the site-path routing, the agent-receiver decision, and the no-external-DB design.
- [ ] This requirement is cross-linked from the implementing PR.

## Validation Apps

```bash
INFINITO_APPS="web-app-checkmk" make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

Smoke: visit `https://monitoring.{{ DOMAIN_PRIMARY }}/` → (SSO) Keycloak chain → Checkmk GUI; open Setup (admin); confirm an LDAP user resolves.

## Prerequisites

Before implementation, the agent MUST read [AGENTS.md](../../AGENTS.md), then [Role Loop](../agents/action/iteration/compose.md) and the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md).

## Implementation Strategy

Execute autonomously after the Open Questions are resolved. Scaffold using [`roles/web-app-openproject/`](../../roles/web-app-openproject/) as the structural template (oauth2 flavor + header SSO + LDAP). Verify all Checkmk env names, the `auth_by_http_header` config mechanism, site-path routing, and the GUI selectors against the pinned upstream version before claiming done.

## Commit Policy

- No git commit until every Acceptance Criterion is checked off.
- When met and `make test` is green, instruct the operator to run `git-sign-push` outside the sandbox. The agent MUST NOT push.

## Context

- Upstream repo: <https://github.com/Checkmk/checkmk>
- Docker docs: <https://docs.checkmk.com/latest/en/introduction_docker.html>
- LDAP: <https://docs.checkmk.com/latest/en/ldap.html>
- Header auth: <https://checkmk.com/werk/7819>
- Closest in-repo analogue: [`roles/web-app-openproject/`](../../roles/web-app-openproject/) (oauth2 + header SSO + LDAP)
