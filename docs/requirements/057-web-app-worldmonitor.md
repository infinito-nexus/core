# 057 - World Monitor Role behind the oauth2-proxy SSO Gate

## User Story

As a platform administrator of Infinito.Nexus, I want [World Monitor](https://github.com/koala73/worldmonitor) integrated as a `web-app-worldmonitor` role behind the platform's Keycloak SSO (via the oauth2-proxy gate) so that users reach the real-time global intelligence dashboard with their existing Infinito.Nexus identity, in compose and in swarm, without a second login.

## Background

World Monitor is an AGPL-3.0 dashboard that aggregates public data feeds (earthquakes, conflicts, markets, vessel tracking and more) on a map. Upstream ships a self-hosted Docker stack of four services.

### Upstream facts established by research

Verified against upstream `main` and release `v2.10.0` (2026-09-08).

| Topic | Finding | Source |
|---|---|---|
| Services | `worldmonitor` (nginx + Node API under supervisord, container port `8080`), `ais-relay` (port `3004`), `redis` (`redis:7-alpine`, `6379`), `redis-rest` (Upstash-compatible REST proxy, port `80`). | [docker-compose.yml](https://github.com/koala73/worldmonitor/blob/main/docker-compose.yml) |
| Published image | Only `ghcr.io/koala73/worldmonitor` is published (semver tags, `linux/amd64` + `linux/arm64`, built from `docker/Dockerfile`). `ais-relay` (`Dockerfile.relay`) and `redis-rest` (`docker/Dockerfile.redis-rest`) have no published image. | [docker-publish.yml](https://github.com/koala73/worldmonitor/blob/main/.github/workflows/docker-publish.yml) |
| User authentication | None in self-hosted mode. `LOCAL_API_MODE=docker` has no Clerk or Convex backend, no local user accounts and no OIDC. The app mints an anonymous `wms_` browser session signed with `WM_SESSION_SECRET`. | [SELF_HOSTING.md](https://github.com/koala73/worldmonitor/blob/main/SELF_HOSTING.md) |
| Mandatory secrets | `RELAY_SHARED_SECRET`, `REDIS_PASSWORD`, `REDIS_TOKEN`, `WM_SESSION_SECRET`. Each container exits on boot when its secret is missing. | SELF_HOSTING.md |
| Admin routes | `/api/local-*` return `403` in Docker mode. Operator settings change only through environment variables plus a container recreate. | SELF_HOSTING.md |
| Reverse proxy | `WM_TRUSTED_PROXY_CIDRS` must name the fronting proxy's network, otherwise `X-Forwarded-For` is ignored and the per-IP LLM cap (50 calls per UTC day) counts the proxy as one client. Invalid values stop the container. | SELF_HOSTING.md |
| CSP | The bundled nginx emits its own `script-src` policy without `'unsafe-inline'`. | SELF_HOSTING.md |
| Data seeding | Redis starts empty. Upstream seeds with `./scripts/run-seeders.sh` run **on the host** (Node 22) against the REST proxy published on `127.0.0.1:8079`, repeated by host cron. The relay runs additional in-container seed loops when `UPSTASH_ALLOW_INSECURE_HTTP=true`. | SELF_HOSTING.md |
| Persistence | One volume, `redis-data`. All content is re-fetchable cache and seed data. | docker-compose.yml |
| LLM | Any OpenAI-compatible endpoint through `LLM_API_URL` (full `/v1/chat/completions` URL), `LLM_API_KEY`, `LLM_MODEL`. | SELF_HOSTING.md |
| MCP | `/api/mcp`, authenticated with `X-WorldMonitor-Key` against `WORLDMONITOR_VALID_KEYS`. The OAuth path is hosted-only. | SELF_HOSTING.md |
| Swarm blockers in the upstream file | `container_name`, `depends_on`, `build:`, `mem_limit`, a host-bound `127.0.0.1:8079` publish. | docker-compose.yml |

### In-repo analogues

- **SSO flavor is `oauth2`** (oauth2-proxy sidecar against Keycloak), as in [`web-app-openclaw`](../../roles/web-app-openclaw/) and [`web-app-checkmk`](029-web-app-checkmk.md). The Keycloak client is provisioned by the platform for every role with `sso.enabled`.
- **Multi-service compose template with a role-built image**: [`web-app-moodle`](../../roles/web-app-moodle/templates/compose.yml.j2). Dockerfile placement and `ARG` wiring follow [dockerfile.md](../contributing/artefact/files/role/dockerfile.md).
- **Shared LiteLLM gateway consumer**: `litellm` service flag plus `secrets.credentials.litellm_api_key` in [`web-app-openclaw`](../../roles/web-app-openclaw/meta/services.yml).
- **Generated credentials**: `meta/secrets.yml` as in [`web-app-openclaw`](../../roles/web-app-openclaw/meta/secrets.yml).

## Proposed Decisions

The operator MUST confirm or change these before implementation starts. Once confirmed they are not re-litigated during implementation.

| # | Decision | Rationale |
|---|---|---|
| 1 | Role `web-app-worldmonitor`, canonical hostname `worldmonitor.{{ DOMAIN_PRIMARY }}`. | Standard single-host convention. |
| 2 | SSO is the **oauth2-proxy gate only**. No native OIDC, no user mapping, no in-app accounts. | Upstream self-hosted mode has no user model to map onto. A later native OIDC switch is the existing `sso.flavor` field, so nothing extra is built for it now. |
| 3 | Every authenticated Keycloak user may enter. No `allowed_groups`, no `meta/rbac.yml`. | The dashboard has no per-user state or admin surface in Docker mode. |
| 4 | The upstream internal mechanisms stay as shipped: the anonymous `wms_` session, the relay shared secret, Redis `requirepass`, the REST proxy bearer token. | They protect service-to-service traffic and are independent of the user boundary. |
| 5 | **Decided 2026-11-07:** `worldmonitor`, `ais-relay`, `redis-rest` and the seeder are all built from the pinned upstream `v2.11.8` source. The published GHCR image is not used. | The GHCR image is frontend-only and proxies `/api` to `api.worldmonitor.app` (evidence below). No fork is maintained. |
| 6 | Redis and the REST proxy run **inside the role stack** with their own generated credentials, not on the shared `svc-db-redis`. | The app speaks only the Upstash REST dialect through the bundled proxy, and upstream runs Redis with `allkeys-lru` eviction that must not apply to other consumers. |
| 7 | Seeding runs **inside the stack** as a periodic seeder service. No host Node, no host cron, no published REST proxy port. | The upstream host-side flow needs a host-bound port and a host runtime, which breaks in swarm and violates service isolation. |
| 8 | The Redis volume persists but is **excluded from backup**. | Content is re-fetchable cache. A restore is a re-seed. |
| 9 | The LLM is wired to the shared LiteLLM gateway when `LITELLM_USABLE`. `OPENROUTER_API_KEY` is not used. | One platform gateway instead of a per-app provider key. |
| 10 | External data-source API keys are optional operator-supplied inventory values, empty when unset. | Upstream degrades gracefully per feed. |
| 11 | `/api/mcp` is **not** registered as a platform MCP server in this requirement. It stays behind the gate and `WORLDMONITOR_VALID_KEYS` stays empty. | The MCP path authenticates with a static key, not with the platform identity. Tracked separately if wanted. |

**Decision #5, decided by the operator on 2026-11-07:** the implementation builds `worldmonitor`, `ais-relay`, `redis-rest` and the seeder from the pinned `v2.11.8` clone instead of pulling the GHCR image. Evidence at `v2.11.8`: the upstream image publish workflow (`docker-publish`, line 171) builds `ghcr.io/koala73/worldmonitor` from `docker/Dockerfile`, which bakes `VITE_WS_API_URL=https://api.worldmonitor.app` (line 26) and `ENV API_UPSTREAM=https://api.worldmonitor.app` (line 69). That image therefore serves only the frontend and proxies `/api/*` to the upstream cloud, which contradicts the in-stack Redis, seeding and isolation of Decisions #6 to #8. The root `Dockerfile` of the same tag builds the full app with its Node API, and `Dockerfile.relay` and `docker/Dockerfile.redis-rest` build the other two services. Keeping the GHCR image would have needed `API_UPSTREAM` pointed at an in-stack API, which upstream does not ship as a separate image.

## Target Schema

### Role layout

```
roles/web-app-worldmonitor/
├── README.md
├── files/playwright/{_shared,playwright.spec,test-guest,test-oidc-login,test-isolation}.js
├── meta/{main,info,account,domains,networks,csp,license,server,services,secrets,variants,volumes}.yml
├── tasks/{main,00_core}.yml
├── templates/{compose.yml.j2,playwright.env.j2}
├── templates/env/{worldmonitor,ais-relay,redis-rest,cache,seeder}.j2
└── vars/main.yml
```

The role ships no `Dockerfile` of its own: per Decision #5 every image builds from an upstream `Dockerfile` inside the pinned clone. Each container reads its own environment file under `templates/env/`.

### `meta/services.yml` excerpt

```yaml
worldmonitor:
  modes:
    compose: { enabled: true }
    swarm:   { enabled: true }
  custom:  true
  version: "2.11.8"
  source_repository: https://github.com/koala73/worldmonitor.git
  source_version: v2.11.8
  name:    worldmonitor
  ports:
    internal: { http: 8080 }
    local:    { http: <free port>, sso: <free port> }
  lifecycle: alpha
sso:
  bond: 1
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
  flavor:  oauth2
  oauth2:
    origin: { host: worldmonitor, port: 8080 }
litellm:
  bond: 1
  enabled: "{{ LITELLM_USABLE }}"
  shared: true
```

### `meta/secrets.yml` credentials

`relay_shared_secret`, `relay_key`, `redis_password`, `redis_token`, `session_secret`, `litellm_api_key`, plus one optional, operator-supplied credential per external API key of Decision #10.

## Acceptance Criteria

### Role layout & images

- [x] `roles/web-app-worldmonitor/` exists per the [Target Schema](#role-layout) and all `meta/*.yml` pass the role-meta lint.
- [x] `worldmonitor` is built from the root `Dockerfile` of the pinned upstream `v2.11.8` source (Decision #5). No `:latest`, no GHCR pull.
- [x] `ais-relay`, `redis-rest` and the seeder are built from the same pinned upstream tag, with every external value passed as a Docker `ARG` per [dockerfile.md](../contributing/artefact/files/role/dockerfile.md).
- [ ] Every image used by the role is declared once in `meta/services.yml` and is found by the image discovery. *The Node base of every upstream `FROM` is the digest-pinned `node` entity, which `iter_role_images` lists for the mirror, the update job and the CVE scan. Every build swaps it in for upstream's unchanged `FROM` through `additional_contexts`, and the generic build base guard of `sys-svc-compose` refuses, between clone and build, a clone whose `FROM` lines leave `services.stack.checkout.build.bases`. Live proof in the final roundtrip.*

### Compose

- [ ] A compose deploy brings `worldmonitor`, `ais-relay`, `redis`, `redis-rest` and the seeder to a steady running state with no manual step.

### Swarm

- [ ] The same role deploys as a swarm stack and reaches the same steady state.
- [ ] The rendered swarm stack contains no `container_name`, no `mem_limit` and no host-bound port publish, and no service fails permanently when its dependencies start after it.
- [ ] The role-built images are available to every swarm node that may schedule the services.

### Secrets

- [x] `RELAY_SHARED_SECRET`, `REDIS_PASSWORD`, `REDIS_TOKEN` and `WM_SESSION_SECRET` are generated through `meta/secrets.yml` and no literal secret value is committed.
- [x] `I_UNDERSTAND_THIS_DISABLES_AUTH` and `ALLOW_UNAUTHENTICATED_RELAY` are not set anywhere in the role.
- [ ] Optional external API keys (`FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FRED_API_KEY`, `EIA_API_KEY`, `ACLED_*`, `NASA_FIRMS_API_KEY`, `AVIATIONSTACK_API`, `TRAVELPAYOUTS_API_TOKEN`, `AISSTREAM_API_KEY`, `CLOUDFLARE_API_TOKEN`) reach the containers that read them when the operator sets them, and the stack is healthy when all are empty.

### Routing & TLS

- [ ] `https://worldmonitor.{{ DOMAIN_PRIMARY }}/` resolves through `sys-svc-proxy` to the `worldmonitor` service and serves the dashboard SPA.
- [ ] `WM_TRUSTED_PROXY_CIDRS` is set to the network the fronting proxy reaches the container from, in compose and in swarm, and the app logs the real client address for a proxied request.
- [ ] The dashboard's live updates (the WebSocket and streaming endpoints it opens) work through the proxy with no console error. *Asserted by `test-live-updates.js`, live proof in the final roundtrip. The `v2.11.8` build opens no browser WebSocket or event stream, because `VITE_WS_RELAY_URL` and `VITE_CONVEX_URL` are unset at build time, so its live updates are the `/api/*` fetches. The spec fails on a gate or proxy refusal of those and on a failed event stream on the canonical host, and off Tor also on any transport or socket failure and console transport error there.*
- [ ] The canonical surface answers with exactly one `Content-Security-Policy` header, and the dashboard renders under it with one expected CSP violation only: the platform policy blocks the upstream Umami tracker that `src/services/analytics.ts` loads from `abacus.worldmonitor.app`, and that `script-src` block is the only violation allowed. *Asserted by `test-oidc-login.js` and, with SSO disabled, `test-guest.js`, live proof in the final roundtrip: `/` answers the signed-in session with exactly one policy, it is the platform policy with every expected directive, and any violation other than that tracker block fails the spec.*

### SSO (Decisions #2 to #4)

- [ ] With SSO enabled, an unauthenticated request to any path, including `/api/*`, is redirected to the Keycloak login.
- [ ] After login the user lands on the dashboard with no further credential prompt.
- [ ] A user with an existing Keycloak session reaches the dashboard without an interactive login. *Asserted by `test-oidc-login.js`, live proof in the final roundtrip: after the login the spec drops only the `_oauth2_proxy` cookies, and the next visit must pass the Keycloak authorization endpoint by redirect and land on the dashboard.*
- [ ] After logout through the platform logout, a request to the dashboard is redirected to the Keycloak login again.
- [ ] With SSO disabled, the dashboard is reachable anonymously and the stack is otherwise unchanged.

### Service isolation

- [x] Only the `worldmonitor` HTTP port is published, bound to the platform bind host. `redis`, `redis-rest` and `ais-relay` publish no port.
- [ ] From outside the role's network, `redis:6379`, `redis-rest:80` and `ais-relay:3004` are unreachable.
- [ ] Redis rejects an unauthenticated command, and `redis-rest` rejects a request without the bearer token.

### Data seeding (Decision #7)

- [ ] After a fresh deploy the dashboard shows seeded data from the key-free feeds with no command run on the host.
- [ ] Seeding repeats on a fixed interval inside the stack, and one hung feed does not block the others.

### Persistence & backup (Decision #8)

- [ ] Seeded data survives a recreate of every container in the stack, in compose and on the swarm storage layer.
- [x] The Redis volume is excluded from the platform backup.

### LLM (Decision #9)

- [ ] When `LITELLM_USABLE` is true, `LLM_API_URL`, `LLM_API_KEY` and `LLM_MODEL` point at the shared LiteLLM gateway with the role's own virtual key, and an intelligence brief request returns generated text.
- [ ] When it is false, the three variables are empty and the stack is healthy.

### Health checks

- [ ] `worldmonitor` has a container healthcheck that fails when either nginx or the Node API is down.
- [ ] `redis` and `redis-rest` have container healthchecks, and the `redis-rest` check fails when Redis is unreachable.
- [x] `ais-relay` has a container healthcheck.

### Variants

- [ ] `meta/variants.yml` covers SSO on and SSO off, and every variant deploys cleanly on a fresh host.

### Playwright

- [x] `test-guest.js` asserts the redirect to Keycloak for the root path and for an `/api/` path.
- [x] `test-oidc-login.js` logs in as `biber`, asserts the map renders, and ends logged out with the dashboard gated again.
- [x] `test-isolation.js` asserts that no internal service answers on the canonical host.
- [ ] `templates/playwright.env.j2` exposes every environment variable the specs read, and `make compose-playwright role=web-app-worldmonitor` exits 0 with no stub test.
- [ ] The same specs pass against the swarm deploy.

### Documentation & quality

- [x] `README.md` documents the gate-only SSO model, the retained internal secrets, the in-stack seeding, the optional API keys with their effect, the image pin and bump policy, and the AGPL-3.0 licence of the upstream.
- [ ] `make test` is green tree-wide.
- [ ] This requirement is cross-linked from the implementing PR.

## Out of Scope

- Native OIDC, user mapping and in-app roles (no upstream support in self-hosted mode).
- Registering `/api/mcp` as a platform MCP server.
- The hosted-only features (Clerk entitlements, premium routes, OAuth for MCP).

## Validation Apps

```bash
make compose-deploy apps=web-app-worldmonitor purge=true full_cycle=true
```

Cross-mode parity follows the [Roundtrip Loop](../../agents/skills/i8-iterate-roundtrip/SKILL.md).

Smoke: visit `https://worldmonitor.{{ DOMAIN_PRIMARY }}/`, pass the Keycloak login, confirm the map shows seeded layers, log out, confirm the gate returns.

## Prerequisites

Before implementation, the agent MUST read [AGENTS.md](../../AGENTS.md), then [Compose Loop](../../agents/skills/i8-iterate-compose/SKILL.md) and the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md).

## Implementation Strategy

Execute autonomously once the [Proposed Decisions](#proposed-decisions) are confirmed. Scaffold from [`roles/web-app-openclaw/`](../../roles/web-app-openclaw/) (oauth2 flavor, generated credentials, LiteLLM consumer) and take the multi-service compose shape from [`roles/web-app-moodle/`](../../roles/web-app-moodle/). Before claiming done, verify against the pinned upstream tag: the environment variable names, whether the published app image contains the seeder scripts, the health endpoint path, and the dashboard selectors used by the specs.

## Commit Policy

- No git commit until every Acceptance Criterion is checked off.
- When met and `make test` is green, instruct the operator to run `git-sign-push` outside the sandbox. The agent MUST NOT push.

## Context

- Upstream repo: <https://github.com/koala73/worldmonitor>
- Self-hosting guide: <https://github.com/koala73/worldmonitor/blob/main/SELF_HOSTING.md>
- Closest in-repo analogues: [`roles/web-app-openclaw/`](../../roles/web-app-openclaw/), [`029-web-app-checkmk.md`](029-web-app-checkmk.md)
