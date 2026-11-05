# 028 - atmo.rsvp (AT Protocol Events) Role + Mobilizon/ActivityPub Bridge

## User Story

As a platform administrator of Infinito.Nexus, I want a self-hostable `web-app-atmo` role that deploys an [atmo.rsvp](https://atmo.rsvp) instance (upstream [flo-bit/atmo-events](https://github.com/flo-bit/atmo-events), the successor to OpenMeet) wired to the platform's existing AT Protocol identity, and a bridge that mirrors calendar events between AT Protocol and Mobilizon, so that events created on my instance appear simultaneously on the AT Protocol (Bluesky) network and the ActivityPub (Fediverse) network from a single source of truth.

## Background

[atmo.rsvp](https://atmo.rsvp) is an open-source, AT-Protocol-native event platform. Its defining property is that **events live on the user's account, not on the app**: an event is a `community.lexicon.calendar.event` record and an RSVP is a `community.lexicon.calendar.rsvp` record, both stored in the user's Personal Data Server (PDS) repo. The atmo app itself is "just a view" (an appview/aggregator) over those records, so RSVPs and events are portable across any app on the open social web.

Upstream facts (from the [repo](https://github.com/flo-bit/atmo-events) and product site, verified June 2026):

- **Stack:** TypeScript + Svelte (with some Astro). `pnpm` monorepo.
- **Runtime target:** Cloudflare Workers (`wrangler.jsonc` present), backed by **D1** (Cloudflare's SQLite) as the aggregator cache and **Meilisearch** (optional) for full-text + geo search.
- **Auth:** "Sign in with Bluesky" — AT Protocol OAuth against the user's PDS / identity. No local password store.
- **External deps:** an AT Protocol PDS (read/write of calendar records), the AT Protocol relay/firehose for aggregation, and optionally Meilisearch.

This requirement covers two related but separable deliverables:

1. **`web-app-atmo`** — a role that runs a self-hosted atmo appview on the platform, reusing the existing AT Protocol identity provided by [`web-app-bluesky`](../../roles/web-app-bluesky/) as the PDS/OAuth source.
2. **`atmo ↔ mobilizon` event bridge** — a component that propagates calendar events between AT Protocol (lexicon records) and ActivityPub (via [`web-app-mobilizon`](../../roles/web-app-mobilizon/), which already serves events at `event.{{ DOMAIN_PRIMARY }}`).

### Closest existing analogues in this repo

| Role | What it provides for this work |
|---|---|
| [`web-app-bluesky`](../../roles/web-app-bluesky/) | The AT Protocol PDS, OAuth identity, and the login-broker sidecar pattern. atmo's "sign in with Bluesky" points here. The multi-entity `services.yml` (pds/web/view/broker/api) is the template for atmo's appview + worker-runtime split. |
| [`web-app-mobilizon`](../../roles/web-app-mobilizon/) | ActivityPub events at `event.{{ DOMAIN_PRIMARY }}`, Postgres+PostGIS, GraphQL API. The bridge target on the ActivityPub side. |

## Proposed Decisions (NOT yet confirmed)

Unlike [024](024-web-app-erpnext.md) / [022](README.md#archive), these are **drafted from a design conversation, not operator-confirmed**. Each is a default the operator can accept or override before implementation starts; they are listed so the agent has a checkable starting point, not as settled contract. See [Open Questions](#open-questions) for the ones with real forks.

| # | Proposed default | Rationale |
|---|---|---|
| 1 | Role id `web-app-atmo`; canonical host `rsvp.{{ DOMAIN_PRIMARY }}`. | Matches the `atmo.rsvp` brand and avoids colliding with Mobilizon's `event.{{ DOMAIN_PRIMARY }}`. Both can coexist as distinct event surfaces. |
| 2 | atmo consumes [`web-app-bluesky`](../../roles/web-app-bluesky/) as its PDS / AT identity source via AT Protocol OAuth; it does **not** ship its own identity store. `sso` is therefore AT-OAuth, not Keycloak OIDC. | atmo is identity-portable by design; the platform already runs a PDS. Re-using it keeps one source of AT identity. |
| 3 | Persistence: the appview's aggregator cache (upstream D1/SQLite) is mapped to a **role-local SQLite volume**, not a central `svc-db-*`. Meilisearch is **optional**, gated on a dynamic `meilisearch` service flag, off by default. | D1 is SQLite-shaped; there is no central SQLite service to reuse, and the cache is rebuildable from the firehose. Search is an opt-in enhancement. |
| 4 | The bridge ships as a **separate component** (own sidecar/role), not inside `web-app-atmo`, gated on `web-app-mobilizon in group_names`. | The appview is useful without the bridge; the bridge is useless without both endpoints. Separable lifecycle, separable failure domain. |
| 5 | Bridge v1 is **one-way: AT Protocol → ActivityPub**. It subscribes to the AT firehose/Jetstream filtered on `community.lexicon.calendar.event` (+ `.rsvp`) and creates/updates the matching Mobilizon event via Mobilizon's GraphQL API. ActivityPub → AT is **deferred** (see Open Question 3). | The AT→AP direction has a clean trigger (firehose) and a clean sink (GraphQL). The reverse direction needs an AT identity to write records as, which is unresolved. |
| 6 | Standard role-meta surface per [008](README.md#archive)/[011](README.md#archive): `meta/{main,info,server,services,schema,users,variants,volumes}.yml`, and the deploy must pass on **both** compose and swarm (per the swarm/compose parity rule). | Every `web-app-*` role lands on the unified meta + dual-mode contract. |

## Open Questions

These have genuine forks and MUST be resolved with the operator before or during implementation. Do not silently pick one and bury it.

1. **Worker runtime.** atmo targets Cloudflare Workers + D1 + (KV?). Self-hosting options, cheapest-first:
   - (a) Run the upstream worker under **`workerd`** (Cloudflare's open-source runtime) or **Miniflare**, with D1 → local SQLite. Closest to upstream, but D1/KV bindings must be shimmed and tracked across upstream bumps.
   - (b) Use a **Node/SvelteKit adapter** build if upstream exposes one (the Svelte portion suggests a possible `@sveltejs/adapter-node` path). Simpler ops, but may not cover the worker-only routes.
   - (c) Fork-and-port. Highest maintenance cost; last resort.
   Pick (a) unless upstream already supports (b). This is the single biggest technical risk and should be spiked first.
2. **Image strategy.** No upstream Docker image is known to exist. Likely a **self-built image** from `files/` (à la [015 Moodle](README.md#archive) / the `web-app-bluesky` login-broker), pinned to a concrete upstream git ref — not `:latest`.
3. **Reverse bridge ownership (ActivityPub → AT).** Writing an AT record requires *an account to write it as*. Whose PDS, whose app-password/OAuth token? Options: a dedicated service account, or per-user delegated write via the login-broker. Unresolved → reverse direction deferred to a follow-up requirement.
4. **De-dup / loop prevention.** With any future bidirectional bridge, an event mirrored A→B must not echo back B→A. v1 (one-way) sidesteps this, but the record↔event id mapping table introduced in v1 MUST be designed so a future reverse path can detect "already mirrored".
5. **Lexicon source of truth for geo/time.** Mobilizon uses PostGIS + its own TZ handling; the lexicon calendar event carries its own location/time fields. The bridge needs an explicit, documented field mapping (start/end/tz/location/title/description/url) — incomplete mapping = silent data loss.

## Target Schema (proposed)

### `web-app-atmo` role layout

```
roles/web-app-atmo/
├── README.md
├── files/
│   ├── atmo/                      # self-built image build context (Open Question 2)
│   │   └── Dockerfile
│   └── playwright/
│       └── test-*.js
├── meta/
│   ├── main.yml
│   ├── info.yml
│   ├── server.yml                 # canonical: rsvp.{{ DOMAIN_PRIMARY }}
│   ├── services.yml
│   ├── secrets.yml
│   ├── users.yml
│   ├── variants.yml
│   └── volumes.yml
├── tasks/
│   └── main.yml
├── templates/
│   ├── compose.yml.j2
│   └── env.j2
└── vars/
    └── main.yml
```

### `meta/services.yml` excerpt (proposed shape)

```yaml
---
# AT identity comes from the platform PDS, not Keycloak.
bluesky:
  enabled: "{{ 'web-app-bluesky' in group_names }}"
  shared:  "{{ 'web-app-bluesky' in group_names }}"
meilisearch:
  enabled: false          # nocheck: dynamic-flag — optional search/geo backend, opt-in
  shared:  false
mobilizon:
  enabled: "{{ 'web-app-mobilizon' in group_names }}"
  shared:  "{{ 'web-app-mobilizon' in group_names }}"
matomo:
  enabled: "{{ 'web-app-matomo' in group_names }}"
  shared:  "{{ 'web-app-matomo' in group_names }}"
design:
  enabled: "{{ 'web-svc-design' in group_names }}"
  shared:  "{{ 'web-svc-design' in group_names }}"
atmo:
  image:   atmo                    # self-built (Open Question 2)
  version: "<upstream-git-ref>"    # concrete ref, never :latest
  name:    atmo
  min_storage: 2GB
  ports:
    local:
      http: <free port>
  run_after:
    - web-app-bluesky
    - web-app-mobilizon
    - web-app-matomo
  lifecycle: alpha
  cpus: "0.5"
  mem_reservation: 256m
  mem_limit: 512m
  pids_limit: 512
```

### Bridge component (per Proposed Decision 4)

A long-running worker (own image, gated on both endpoints present) that:

- subscribes to the AT firehose / Jetstream, filtered to collections `community.lexicon.calendar.event` and `community.lexicon.calendar.rsvp`;
- maps each record to a Mobilizon event (field mapping per Open Question 5) and upserts via Mobilizon's GraphQL API;
- persists a `{ at_uri ↔ mobilizon_event_id }` mapping (role-local SQLite) so updates/deletes track and a future reverse path can dedup.

## Acceptance Criteria

### Phase 1 — `web-app-atmo` deploys and serves (MVP)

- [x] `roles/web-app-atmo/` exists with the standard meta surface and passes the repo's role-meta lint (per [008](README.md#archive)/[011](README.md#archive)). `roles/web-app-atmo/meta/` carries `main`, `info`, `domains`, `csp`, `services`, `secrets`, `users`, `variants`, `volumes`, `networks` and `license`, where `domains`, `csp` and `secrets` are the current names of the proposed `server` and `schema` files, and the role-meta suite `tests/lint/ansible/roles/meta/` passes over the tree (141 tests, 296 subtests).
- [x] Open Question 1 (worker runtime) is resolved and the chosen approach is recorded in the role README.
- [ ] `rsvp.{{ DOMAIN_PRIMARY }}` resolves through `sys-svc-proxy` and returns HTTP 200 on `GET /` with the atmo appview HTML.
- [x] The image is self-built from `files/` and pinned to a concrete upstream git ref in `meta/services.yml` (no `:latest`).
- [ ] The aggregator cache persists to a role-local volume declared in `meta/volumes.yml` and survives a container restart.
- [ ] The deploy succeeds in **both** compose and swarm iteration loops (swarm/compose parity rule), `make autoformat` + `make test` green.

### Phase 1 — AT identity wiring

- [ ] "Sign in with Bluesky" completes an AT Protocol OAuth round-trip against the platform PDS provided by [`web-app-bluesky`](../../roles/web-app-bluesky/), and an authenticated user can create a `community.lexicon.calendar.event` record that is written to their PDS repo.
- [ ] A created event is visible in the atmo appview after firehose/aggregator catch-up.
- [x] CSP `connect-src` whitelists the PDS host, the appview host, and any `wss://` firehose endpoint atmo connects to.

### Phase 2 — AT → ActivityPub bridge (one-way)

- [ ] A bridge component exists, gated on both `web-app-atmo` and `web-app-mobilizon` being in `group_names`; absent either, it is not scheduled and the deploy still succeeds.
- [x] The field mapping (start/end/tz/location/title/description/url, per Open Question 5) is documented in the bridge README; unmapped fields are listed explicitly, not dropped silently.
- [ ] Creating a calendar event on the atmo instance results, within a bounded delay, in a matching event published by [`web-app-mobilizon`](../../roles/web-app-mobilizon/) at `event.{{ DOMAIN_PRIMARY }}` and thus federated over ActivityPub.
- [ ] Updating the source AT record updates the mirrored Mobilizon event (mapping table resolves the target id); deleting the source record removes or cancels the Mobilizon event.
- [x] The `{ at_uri ↔ mobilizon_event_id }` mapping persists to a role-local store and is designed to support future dedup for a reverse path (Open Question 4).
- [ ] Before the role leaves `pre-alpha`, the bridge signs in to Mobilizon with a dedicated account and its own secret, which `web-app-mobilizon` provisions with a profile, and no bridge env file carries a credential of `users.platform_administrator`. *The bridge's account is `web-app-mobilizon-atmo-bridge` (Mobilizon username `atmo_bridge`, `accounts: []`) in [web-app-mobilizon/meta/users.yml](../../roles/web-app-mobilizon/meta/users.yml), and the inventory pins it its own password. [test_bridge_env.py](../../tests/unit/python/roles/web-app-atmo/templates/test_bridge_env.py) renders [env/bridge.j2](../../roles/web-app-atmo/templates/env/bridge.j2) and finds the account's email and password with no credential of the platform administrator; the same render of the former template reports both keys. [tasks/01_design.yml](../../roles/web-app-mobilizon/tasks/01_design.yml) creates it with a profile and the Mobilizon role `user` through [account.exs](../../roles/web-app-mobilizon/files/elixir/account.exs) whenever the atmo `bridge` flag is on, which [test_accounts.py](../../tests/unit/python/roles/web-app-mobilizon/test_accounts.py) resolves for atmo absent, bridge off and bridge on. Ticking needs one deploy of `web-app-atmo` with `web-app-mobilizon` and `web-app-bluesky` in which the account script runs and the bridge's heartbeat follows a successful login.*

### Deferred to a follow-up requirement (NOT in scope here)

- ActivityPub → AT Protocol direction (blocked on Open Question 3: AT write identity). Deferred to a follow-up requirement.
- Bidirectional sync with loop prevention. Deferred to a follow-up requirement.
- RSVP mirroring across protocols (Mobilizon participation ↔ `community.lexicon.calendar.rsvp`). Deferred to a follow-up requirement.

## Implementation Notes

Recorded from the first implementation round, upstream read at commit `83e3d1067a5c13de2e850ad290f62de82a727923`. Each item departs from or settles a proposal above and awaits operator confirmation.

- **Open Question 1:** option (a). Upstream reads its bindings from `cloudflare:workers`, so no Node adapter build exists. The worker runs unchanged under `wrangler dev --local` (workerd plus Miniflare's D1, KV and R2), persisted to the `data` volume. Details: [README.md](../../roles/web-app-atmo/README.md#worker-runtime).
- **Open Question 2:** self-built from `roles/web-app-atmo/files/Dockerfile`, pinned by commit in `services.atmo.ref`; upstream publishes no tags.
- **Cron:** Wrangler's local mode fires no cron triggers, so a `cron` sidecar posts to `/api/cron`.
- **Decision 3:** upstream no longer uses Meilisearch; search runs on SQLite FTS inside the aggregator, so no `meilisearch` flag exists.
- **Decision 4:** the bridge ships as the `bridge` sidecar of `web-app-atmo`, gated on `web-app-mobilizon` and `web-app-bluesky` in `group_names`, because its source is the platform PDS.
- **Decision 5:** the bridge reconciles against the platform PDS (`listRepos` revisions plus `listRecords`) instead of subscribing to Jetstream. Deletes fall out of the comparison, and a PDS the public relay does not crawl still mirrors.
- **Mobilizon identity:** the bridge publishes as the platform administrator through Mobilizon's database login, which is off whenever Mobilizon's native login method is off. The sidecar parses records any platform PDS user can write while it holds the global administrator password, so a dedicated bridge account replaces this before `alpha` (operator, 2026-11-04).
- **Lifecycle:** `pre-alpha` until a deploy round proves the `alpha` criteria.

## Cross-linking

- Upstream: [flo-bit/atmo-events](https://github.com/flo-bit/atmo-events) · product: [atmo.rsvp](https://atmo.rsvp) · lexicon: `community.lexicon.calendar.event` / `.rsvp`.
- Depends on: [`web-app-bluesky`](../../roles/web-app-bluesky/) (AT identity/PDS), [`web-app-mobilizon`](../../roles/web-app-mobilizon/) (ActivityPub bridge target).
- Link the implementing PR(s) back to this file when work starts.

## See Also

- How agents process requirements: [requirements.md](../../agents/skills/i8-requirement-implement/SKILL.md)
- Requirement format: [requirements.md](../contributing/requirements.md)
