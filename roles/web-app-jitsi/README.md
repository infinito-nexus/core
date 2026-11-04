# Jitsi Meet

## Description

[Jitsi Meet](https://jitsi.org/) is an open-source, end-to-end-encryptable video conferencing platform. Rooms run over WebRTC with a central Selective Forwarding Unit (jvb), an XMPP server (prosody) for signalling, and a conference focus daemon (jicofo).

## Overview

This role deploys the official `jitsi/{web,prosody,jicofo,jvb}` images as a single-domain Jitsi Meet stack. With SSO enabled, the oauth2-proxy gate admits every realm user to the vhost. With `services.keycloak_adapter.enabled` also true, the role builds the [nordeck jitsi-keycloak-adapter](https://github.com/nordeck/jitsi-keycloak-adapter) (Apache-2.0) and switches prosody to `AUTH_TYPE=jwt`. In the LDAP-only variant, prosody uses the image's own `AUTH_TYPE=ldap` path (`mod_auth_cyrus` against the saslauthd the `LDAP_*` variables of [env.j2](./templates/env.j2) configure). The web container sits behind the central openresty reverse proxy at `meet.{{ DOMAIN_PRIMARY }}`; the media plane (jvb) publishes UDP `10000/udp` on the host.

## Features

- **SSO gate:** With `services.sso.enabled`, oauth2-proxy admits every realm user to the vhost.
- **Moderators from Keycloak:** With `services.keycloak_adapter.enabled` (on in variant 0), Jitsi's `TOKEN_AUTH_URL` sends the "I am the host" step to the adapter. The adapter signs an HS256 JWT for every realm user; `context.user.moderator` is true only for members of the `web-app-jitsi` `administrator` group. Prosody's `token_affiliation` module makes them owners and every other token holder a named member, and `ENABLE_AUTO_OWNER=false` keeps jicofo from promoting the first participant, so a non-moderator joins under their Keycloak name and waits in the lobby for a moderator.
- **LDAP direct-bind variant:** `meta/variants.yml` V3 sets `AUTH_TYPE=ldap`, so prosody binds against `svc-db-openldap` through saslauthd with `LDAP_FILTER` built from `LDAP.FILTERS.USERS.ALL` and `LDAP.USER.ATTRIBUTES.ID`.
- **Three persona surfaces:** `guest` lands on the public landing without a room, `biber` and `administrator` reach the prejoin lobby behind the SSO gate.
- **Self-contained Prosody:** Component secrets for jicofo, jvb, jigasi and jibri are pre-generated via `meta/secrets.yml` so XMPP auth is stable across redeploys.

### Keycloak adapter

The adapter is built from the upstream sources at `services.keycloak_adapter.ref` on the multi-arch `denoland/deno` image, with the role's own [context.ts](./templates/keycloak_adapter/context.ts.j2) baked in. [forwarded_scheme.ts](./files/keycloak_adapter/forwarded_scheme.ts) rewrites the upstream `adapter.ts` at build time so the `redirect_uri` carries the scheme from `X-Forwarded-Proto` instead of a hard-coded `https`, and fails the build when upstream moves one of the three rewritten lines. The web container serves `/oidc/{redirect,auth,tokenize}` through [nginx.conf.j2](./templates/keycloak_adapter/nginx.conf.j2) and the callback page `/static/oidc-adapter.html` from [oidc-adapter.html.j2](./templates/keycloak_adapter/oidc-adapter.html.j2). Enabling the switch on an existing inventory needs the `jwt_app_secret` credential, so regenerate the inventory first.

## Developer Notes

Variant matrix lives in [variants.yml](./meta/variants.yml). Service flags, ports, and image pins in [services.yml](./meta/services.yml). Credentials declared in [secrets.yml](./meta/secrets.yml).

### Persona contract opt-outs

The `biber` and `administrator` Playwright personas are gated on `services.sso.enabled`. When SSO is off, [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. Two reasons:

- **V2 (no auth)**: every service is off; there is no auth chain to drive end-to-end.
- **V3 (LDAP only)**: Jitsi has no in-app HTTP OIDC adapter, so the prosody LDAP bind happens inside the XMPP signalling layer when the user joins a room. The persona helpers only model the OIDC redirect chain through Keycloak, so the LDAP-only variant cannot be exercised via the shared persona helpers.

The `guest` persona is always live (no auth chain assumption) and the canonical-landing baseline test runs unconditionally.

## Further Resources

- [Jitsi Meet Project](https://jitsi.org/)
- [docker-jitsi-meet (upstream)](https://github.com/jitsi/docker-jitsi-meet)
- [Jitsi prosody plugins (jitsi-contrib)](https://github.com/jitsi-contrib/prosody-plugins)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/KcFbkdE1pGPPARuyLdS4fU)
