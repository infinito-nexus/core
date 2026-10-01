# Social Home

## Description

Deploy **[Social Home](https://github.com/social-home-io/socialhome)**, a privacy-first federated social platform built for a single household. One container, an embedded SQLite database, and peer-to-peer federation between households over Ed25519-signed WebRTC data channels — no ActivityPub, no message broker, no object store.

This is **not** [jaywink/socialhome](https://github.com/jaywink/socialhome), the Django content-hub project of the same name. Different codebase, different protocol, different maintainers.

## Overview

The role runs the upstream `ghcr.io/social-home-io/socialhome` image behind the central reverse proxy on its own canonical domain. Everything the application keeps lives in one volume at `/data`: the SQLite database, uploaded media, and installed apps. The administrator account is provisioned from the role's generated credential, and the role finishes the upstream first-boot wizard over the API so the front page renders a login form instead of a setup screen.

A rendered `socialhome.toml` is mounted alongside the environment file. It carries exactly one setting — `[standalone].external_url` — because that value has no `SH_*` environment equivalent upstream and federation pairing returns `422 NOT_CONFIGURED` without it.

## Features

- **Single Container:** No database server, no cache, no worker, no object store. SQLite in one volume.
- **Headless Provisioning:** The administrator is seeded from the role's credential and the first-boot wizard is completed over the API, so no manual click-through is required.
- **Federation Ready:** The rendered `socialhome.toml` publishes the instance's external URL, which is what QR pairing hands to peer households.
- **Own STUN/TURN:** When `web-svc-coturn` is part of the deployment, WebRTC uses it with time-limited HMAC credentials instead of a third-party STUN server.
- **No Outbound Surprises:** The upstream app catalog fetch to github.com is disabled. Without `web-svc-coturn` the app still falls back to its built-in Google STUN server, since suppressing the variable entirely would leave WebRTC with none at all.
- **Desktop Integration Hooks:** This README ensures inclusion in the Web App Desktop overview.

## Limitations

- The role has never been deployed. `lifecycle` is `alpha`, so CI deploys it from the next run on; that run is its first execution. See [TODO.md](TODO.md).
- No SSO. The application authenticates against its own user table and has no OIDC client, so the reverse proxy is not SSO-gated — federation endpoints must stay publicly reachable.
- The application ships no logout control at `2026.6.16`, so the Playwright administrator persona is declared blocked.

## Further Resources

- [Social Home source](https://github.com/social-home-io/socialhome)
- [Published container images](https://github.com/social-home-io/socialhome/pkgs/container/socialhome)
- [TURN REST API credential scheme](https://datatracker.ietf.org/doc/html/draft-uberti-behave-turn-rest-00)
