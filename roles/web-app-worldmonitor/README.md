# World Monitor

## Description

[World Monitor](https://github.com/koala73/worldmonitor) is a real-time global intelligence dashboard. It plots public news, conflict, aviation, shipping, natural hazard and market feeds on an interactive map and in configurable panels, and can summarise the situation through a language model.

## Overview

This role runs the self-hosted stack of the pinned upstream commit (`ref` in [`meta/services.yml`](./meta/services.yml)) behind the platform proxy:

- **worldmonitor:** the dashboard SPA served by nginx together with the Node API that answers `/api/*`.
- **ais-relay:** the WebSocket relay for live vessel positions and other streaming feeds.
- **redis-rest:** the Upstash-compatible REST bridge the app and the seeders use to reach Redis.
- **cache:** Redis with a password, memory-capped with an LRU policy. The entity is named `cache` because the shared compose base already names its embedded service `redis`.
- **seeder:** runs the upstream `scripts/run-seeders.sh` in a loop inside the stack, so fresh data arrives without any command on the host.

Every image is built from the pinned upstream clone. The image published on GHCR serves only the frontend and proxies `/api/*` to `api.worldmonitor.app`, so it cannot run self-contained; building the API, relay, REST bridge and seeders from the same commit keeps all traffic inside the stack.

### Single sign-on

World Monitor has no account system and speaks no OIDC. When Keycloak is part of the deployment the oauth2 gate guards the whole domain, including `/api/*`; every signed-in platform user reaches the dashboard and nobody else does. Logout goes through the platform logout (`/oauth2/sign_out`), because the dashboard has no logout control of its own. Without Keycloak the dashboard is public.

The upstream client sends its public `/api/*` reads with `credentials: 'omit'`, a cache key for the upstream CDN, so the browser drops the gate cookie and the gate answers them with a login redirect. With SSO on, the platform injects [`files/javascript/javascript.js`](./files/javascript/javascript.js) into the dashboard page; it raises exactly those fetches to the dashboard's own `/api/` routes to `same-origin` credentials before the client boots, so they carry the gate session and no route needs a bypass. Requests to other origins and every other credentials mode pass through unchanged.

### Internal secrets

The upstream authentication between its own services stays enabled: `RELAY_SHARED_SECRET`, `REDIS_PASSWORD`, `REDIS_TOKEN` and `WM_SESSION_SECRET` are generated through [`meta/secrets.yml`](./meta/secrets.yml). `I_UNDERSTAND_THIS_DISABLES_AUTH` and `ALLOW_UNAUTHENTICATED_RELAY` are never set. Only the `worldmonitor` HTTP port is published, bound to the platform bind host; Redis, the REST bridge and the relay stay on the role network.

### Seeding

The seeder starts every seeder script once per `services.seeder.interval_seconds`. Each standalone seeder is capped by `services.seeder.timeout_seconds` (`SEED_TIMEOUT` upstream), so one hung feed cannot block the ones after it. Seeded data lives in the `cache_data` volume, which survives container recreation and is excluded from the platform backup, because the seeder rebuilds it.

### Optional API keys

The key-free feeds work without any key. Each key in [`meta/secrets.yml`](./meta/secrets.yml) that the operator sets unlocks the matching feeds; an empty key leaves them out and the stack stays healthy:

| Credential | Effect |
|---|---|
| `finnhub_api_key` | Primary equity quotes and search |
| `alpha_vantage_api_key` | Equity fallback and market seeders |
| `fred_api_key` | FRED economic indicators |
| `eia_api_key` | EIA energy data |
| `acled_email`, `acled_password`, `acled_access_token` | ACLED conflict and unrest events |
| `nasa_firms_api_key` | NASA FIRMS wildfire detections |
| `aviationstack_api` | Aviation data |
| `travelpayouts_api_token` | Flight price search |
| `aisstream_api_key` | Live vessel positions, passed to the app and the relay |
| `cloudflare_api_token` | Internet outage data, needs paid Cloudflare Radar access |

Use a dedicated read-only token for `cloudflare_api_token` and never the platform DNS token.

### Language model

When LiteLLM is usable, `LLM_API_URL`, `LLM_API_KEY` and `LLM_MODEL` point at the shared LiteLLM gateway with the role's own virtual key. Otherwise the three variables stay empty and the AI summaries are off.

### Image pin and bump policy

`services.worldmonitor.ref` pins a full upstream commit of the default branch, declared as `ref_kind: commit`, and the clone fetches exactly that commit at depth 1. Every image the stack builds is tagged with the same commit, so the image tag always matches the clone it was built from. The repository updater moves the `ref` to the tip of the upstream default branch, which moves the clone and every image tag together.

The role pins a commit and not a release tag because the upstream build refuses a live-pulse snapshot older than 10 days (`MAX_LIVE_PULSE_SNAPSHOT_AGE_DAYS` in `scripts/build-crawlable-corpus.mjs`), measured against the build date, so every tag stops building 10 days after its snapshot was captured. Return to `ref_kind: tag` once upstream ships a tag that builds independent of the date.

## Features

- **Live map:** Conflicts, hazards, flights, vessels and infrastructure on one interactive map.
- **Panels:** News, markets, energy and situation panels next to the map.
- **In-stack data:** Seeding, caching and the REST bridge run inside the stack, with no call to the upstream cloud API.
- **Platform login:** The oauth2 gate admits signed-in platform users only.

## Further Resources

- [Upstream repository](https://github.com/koala73/worldmonitor)
- [Self-hosting guide](https://github.com/koala73/worldmonitor/blob/v2.11.8/SELF_HOSTING.md)
- [Licence: AGPL-3.0-only](https://github.com/koala73/worldmonitor/blob/de602d000d9e10e7da651884bb589d2ad55f3593/LICENSE)

## Persona contract opt-outs

The `biber` persona passes the oauth2 gate and reaches the dashboard; the `guest` persona is turned away at the gate. The `administrator` persona is blocked in [`templates/playwright.env.j2`](./templates/playwright.env.j2): the gate admits every platform user alike and the dashboard has no admin surface, so an administrator journey would only repeat the biber one.
