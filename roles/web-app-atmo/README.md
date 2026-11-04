# atmo.rsvp

## Description

[atmo.rsvp](https://atmo.rsvp) is an open-source event platform built on the AT Protocol. An event is a `community.lexicon.calendar.event` record and an RSVP is a `community.lexicon.calendar.rsvp` record, both stored in the repository of the user's own Personal Data Server (PDS). The atmo app is an appview over those records, so events and RSVPs stay portable across every app of the open social web.

## Overview

This role builds atmo from a pinned upstream commit and runs it behind the front proxy on the `rsvp` subdomain of the primary domain. A cron sidecar drives the ingest cycle that upstream runs as a Cloudflare cron trigger. When [Mobilizon](../web-app-mobilizon/) and [Bluesky](../web-app-bluesky/) run on the same host, a bridge sidecar mirrors the calendar events of the platform PDS into Mobilizon, which federates them over ActivityPub. The bridge and its field mapping are described in [Bridge.md](./Bridge.md).

## Features

- **Portable events:** Events and RSVPs live in the users' own PDS repositories; the appview only indexes them.
- **Sign in with Bluesky:** AT Protocol OAuth against the user's PDS, including the platform PDS of `web-app-bluesky`.
- **Self-hosted worker runtime:** The upstream Cloudflare Worker runs under `workerd` through Wrangler's local mode, with D1, KV and R2 kept as SQLite files on a role-local volume.
- **Platform sign-up:** New accounts are created on the platform PDS when `web-app-bluesky` is deployed; without it sign-up is switched off instead of sending users to a third-party PDS.
- **ActivityPub mirror:** An optional one-way bridge publishes the platform's AT Protocol events as Mobilizon events.

## Worker runtime

Upstream targets Cloudflare Workers only: the code reads its bindings from `cloudflare:workers`, persists to two D1 databases, two KV namespaces and an R2 bucket, and fires its ingest cycle from a cron trigger. A Node adapter build is therefore not available without porting the code.

The role runs the upstream build unchanged under `wrangler dev --local`, which is `workerd` plus Miniflare's local implementations of D1, KV, R2 and the rate limiter. Wrangler reads the bindings from upstream's own `wrangler.jsonc`, so a version bump needs no binding shim. The relevant flags:

- `--persist-to /data` keeps every binding in the `data` volume, so the aggregator cache, the OAuth sessions and the OG image cache survive a restart.
- `--local-upstream` and `--upstream-protocol https` make the worker see its public origin, which SvelteKit's origin checks and the OAuth client both compare against.
- `CLOUDFLARE_INCLUDE_PROCESS_ENV=true` hands the container environment to the worker, so the secrets come from the role's env file and override the upstream values in `wrangler.jsonc`.

Wrangler's local mode does not fire cron triggers. The `cron` sidecar posts to `/api/cron` with the cron secret on the interval set in `services.cron.interval_seconds`, which is exactly what upstream's scheduled handler does.

The Miniflare stores are SQLite files, so the role pins itself to the manager node, keeps its volumes off NFS and runs one replica of each service.

## Single sign-on

This role does not configure OIDC against `web-app-keycloak` or LDAP against `svc-db-openldap`. atmo has no local accounts: users sign in with AT Protocol OAuth at their own PDS, and the PDS of `web-app-bluesky` is where the platform's accounts live. Moderation rights are granted to DIDs listed in `services.atmo.moderator_dids`, not to an in-app role, so there is no Keycloak group to map either. Placing atmo behind the SSO proxy would break the OAuth callbacks and the public client metadata the PDS fetches.

## Persona contract opt-outs

The `biber` and `administrator` personas are blocked. `meta/services.yml` pins `sso.enabled: false` and `logout.enabled: false`, the Keycloak personas own no PDS account to sign in with, and atmo has no admin surface outside the DID-based moderation. The Playwright suite covers the public appview, the OAuth client metadata and the cron guard instead.

## Developer notes

See [Bridge.md](./Bridge.md) for the AT Protocol to ActivityPub bridge and its field mapping.

## Further resources

- [atmo.rsvp](https://atmo.rsvp)
- [atmo-events on GitHub](https://github.com/flo-bit/atmo-events)
- [Wrangler local development](https://developers.cloudflare.com/workers/development-testing/)
