# 030 - Jellyfin Role with LDAP / OIDC SSO

## User Story

As a platform administrator of Infinito.Nexus, I want [Jellyfin](https://jellyfin.org) integrated as a `web-app-jellyfin` role with Keycloak-backed Single Sign-On so that users can stream the media server behind the platform's central identity, validated end-to-end with Playwright personas.

## Background

[Jellyfin](https://jellyfin.org) is a free, open-source media server. The official `jellyfin/jellyfin` container is Debian-based, stores everything in an internal SQLite DB (**no external database**), and persists three volumes: `/config`, `/cache`, `/media`.

### Upstream facts established by research

| Topic | Finding | Source |
|---|---|---|
| Image | `jellyfin/jellyfin` (Docker Hub + `ghcr.io`); tags `latest`, `X.Y`, `X.Y.Z`. Pin a concrete `10.x` patch. | [Container install](https://jellyfin.org/docs/general/installation/container/) |
| Config | `JELLYFIN_*` env (double-underscore nesting), `JELLYFIN_PublishedServerUrl`, `TZ`; runs as `PUID/PGID`. | [Configuration](https://jellyfin.org/docs/general/administration/configuration/) |
| Ports | `8096` (HTTP web), `8920` (optional HTTPS), `7359/udp` + `1900/udp` (client/service discovery). | [Container install](https://jellyfin.org/docs/general/installation/container/) |
| Database | None external — internal SQLite under `/config`. | [Configuration](https://jellyfin.org/docs/general/administration/configuration/) |
| Native auth | Local Jellyfin users only — **no native OIDC/LDAP**. | [Discussion #16470](https://github.com/orgs/jellyfin/discussions/16470) |
| LDAP plugin | [`jellyfin-plugin-ldapauth`](https://github.com/jellyfin/jellyfin-plugin-ldapauth) — official-catalog plugin; **works on ALL clients** (web + native apps). | [LDAP self-hosting](https://joeeey.com/blog/selfhosting-sso-ldap-part-3/) |
| OIDC/SSO plugin | [`9p4/jellyfin-plugin-sso`](https://github.com/9p4/jellyfin-plugin-sso) — OIDC/SAML one-click, **web UI only** (native apps cannot use it); third-party. | [plugin-sso](https://github.com/9p4/jellyfin-plugin-sso) |
| oauth2-proxy gate | Breaks native apps (they authenticate with API tokens, cannot run the browser OIDC flow). Not suitable as the sole gate for a media server. | [Discussion #16470](https://github.com/orgs/jellyfin/discussions/16470) |

### In-repo analogues

- Because Jellyfin has no native SSO and its apps use API tokens, the **LDAP plugin against the central `svc-db-openldap`** is the "works everywhere" path — closest in spirit to roles that consume central LDAP. The optional OIDC web-SSO plugin maps to the platform Keycloak.
- No external DB consumer (like Checkmk).

## Confirmed Decisions

These decisions were confirmed by the operator before implementation starts and are NOT subject to re-litigation during implementation.

| # | Decision | Rationale |
|---|---|---|
| 1 | Canonical hostname `media.{{ DOMAIN_PRIMARY }}`. | Standard single-host convention. |
| 2 | **Both** auth plugins: `jellyfin-plugin-ldapauth` (central OpenLDAP, all clients) **and** `9p4/jellyfin-plugin-sso` (Keycloak OIDC, web one-click). | Operator decision: LDAP gives every client (incl. native apps) a platform identity; the OIDC plugin adds one-click web sign-in. |
| 3 | Media library on a **named Docker volume** (`/media`), plus `/config` + `/cache`. | Operator decision: self-contained v1; libraries added in-app. |
| 4 | **CPU transcoding only** (no GPU passthrough). | Operator decision: smallest, host-portable surface. |
| 5 | Image `jellyfin/jellyfin` pinned to a concrete stable `10.x` patch (no `:latest`). | Standard upstream-pin policy. |
| 6 | No external DB; internal SQLite under `/config`. | Jellyfin bundles SQLite. |

## Target Schema

### Role layout

```
roles/web-app-jellyfin/
├── README.md
├── files/playwright/*.js
├── meta/{main,info,server,services,schema,users,rbac,variants,volumes}.yml
├── tasks/{main,01_core}.yml
├── templates/{compose.yml.j2,env.j2,playwright.env.j2}
└── vars/main.yml
```

## Acceptance Criteria

### Routing & TLS

- [ ] `media.{{ DOMAIN_PRIMARY }}` resolves through `sys-svc-proxy` to Jellyfin (`8096`); `GET /` returns the Jellyfin web UI; `JELLYFIN_PublishedServerUrl` is set to the canonical URL.
- [ ] The role emits a `Content-Security-Policy` header on the canonical surface.

### Role layout & image

- [ ] `roles/web-app-jellyfin/` exists per the [Target Schema](#role-layout); image pinned to a concrete `10.x` patch (no `:latest`).
- [ ] All `meta/*.yml` exist and pass the role-meta lint.

### Bootstrap

- [ ] First run reaches a steady running state with `/config` + `/cache` (+ media per Q2) persisted; the initial-setup wizard is bypassed or a first admin is seeded where supported.

### Authentication (Decision #2)

- [ ] The chosen auth integration is provisioned non-interactively: for LDAP, `jellyfin-plugin-ldapauth` is installed and configured against `svc-db-openldap` (server/bind/search/attributes); for the OIDC plugin, it is installed and pointed at Keycloak.
- [ ] An LDAP/SSO user can sign in and reach the Jellyfin home; a dedicated Playwright scenario (gated on the chosen service) covers it.

### Variants

- [ ] `meta/variants.yml` defines three variants (V1 all auth on, V2 all-false, V3 ldap-only); all deploy cleanly on a fresh box.

### Playwright

- [ ] Guest + authenticated persona(s) per the [playwright contract](../contributing/artefact/files/role/playwright.specs.js.md); `templates/playwright.env.j2` exposes every read env var; `make compose-playwright role=web-app-jellyfin` exits 0 with no stub tests and a clean logged-out final state.

### Health & quality

- [ ] Stack steady across all three variants; `make test` green tree-wide.

### Documentation

- [ ] `README.md` documents image + bump policy, the auth approach + its client-coverage caveat (web-only vs all-clients), the media-storage decision, transcoding, and the no-external-DB design.
- [ ] This requirement is cross-linked from the implementing PR.

## Validation Apps

```bash
INFINITO_APPS="web-app-jellyfin" make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

Smoke: visit `https://media.{{ DOMAIN_PRIMARY }}/` → Jellyfin loads → sign in via the chosen integration → reach the home/library surface.

## Prerequisites

Before implementation, the agent MUST read [AGENTS.md](../../AGENTS.md), then [Role Loop](../agents/action/iteration/role.md) and the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md).

## Implementation Strategy

Execute autonomously after the Open Questions are resolved. Verify the plugin install + config mechanism (plugin DLL placement under `/config/plugins`, the plugin configuration XML schema, and the catalog/version) against the pinned upstream plugin release before claiming done.

## Commit Policy

- No git commit until every Acceptance Criterion is checked off.
- When met and `make test` is green, instruct the operator to run `git-sign-push` outside the sandbox. The agent MUST NOT push.

## Context

- Upstream site: <https://jellyfin.org>
- Container docs: <https://jellyfin.org/docs/general/installation/container/>
- LDAP plugin: <https://github.com/jellyfin/jellyfin-plugin-ldapauth>
- OIDC/SSO plugin: <https://github.com/9p4/jellyfin-plugin-sso>
