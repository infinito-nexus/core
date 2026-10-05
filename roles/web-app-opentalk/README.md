# OpenTalk

## Description

[OpenTalk](https://opentalk.eu/) is a sovereign open-source video conferencing platform developed by the Heinlein Group. It combines a Rust controller, a LiveKit-based WebRTC media server, and a React web frontend.

## Overview

This role deploys the OpenTalk stack using Docker Compose and exposes the web frontend at `open.talk.{{ DOMAIN_PRIMARY }}` through the central reverse proxy. It runs the Rust controller, the LiveKit WebRTC media server, the React web frontend, a dedicated Redis, a dedicated MinIO bucket for controller assets, a RabbitMQ broker, and the OpenTalk recorder for meeting MP4 archives. The deployment integrates with the shared Keycloak realm via OIDC and reuses `svc-db-postgres` and `web-svc-coturn` for relational data and STUN/TURN. For identity wiring details see [IAM.md](docs/IAM.md) and [LDAP.md](docs/LDAP.md).

## Features

- **Sovereign Video Conferencing:** Self-host meetings under your own domain without external SaaS dependency.
- **WebRTC Media via LiveKit:** Real-time audio, video, and screen sharing through a high-performance SFU.
- **Single Sign-On:** Frontend and controller share one Keycloak client and realm.
- **Federated User Lookup:** Invitee search resolves through the Keycloak admin Web API, so any user federated from OpenLDAP into Keycloak becomes findable inside OpenTalk.
- **OpenCloud File Integration:** Pick files from OpenCloud in a meeting without re-authenticating when `web-app-opencloud` is deployed alongside.
- **Meeting Recordings:** A dedicated recorder consumes recording jobs from the RabbitMQ queue and stores MP4 archives in MinIO.
- **Shared Infrastructure:** Reuses `svc-db-postgres` for relational data and `web-svc-coturn` for STUN and TURN.

## Developer Notes

See [IAM.md](docs/IAM.md) for the OIDC and Keycloak admin Web API setup, and [LDAP.md](docs/LDAP.md) for the LDAP federation chain. Pending follow-up work is tracked in [TODO.md](TODO.md).

## Further Resources

- [opentalk.eu](https://opentalk.eu/)
- [OpenTalk documentation](https://docs.opentalk.eu/)
- [OpenTalk setup template](https://gitlab.opencode.de/opentalk/ot-setup)

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). The OpenTalk frontend is a public-client OIDC single-page app — the container env carries nothing but the issuer and the client id, there is no server-side session and no HTML login form — so the role drives it with its own redirect-racing helper keyed on `LOGIN_*` / `BIBER_*` instead of the `ADMIN_*` pair the shared helper expects, and the browser-side session leaves the contract's in-app logout leg without a target. Both personas' Keycloak → dashboard chain is covered by [files/playwright/test-sso-login.js](./files/playwright/test-sso-login.js).
