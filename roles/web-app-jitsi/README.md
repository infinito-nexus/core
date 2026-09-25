# Jitsi Meet

## Description

[Jitsi Meet](https://jitsi.org/) is an open-source, end-to-end-encryptable video conferencing platform. Rooms run over WebRTC with a central Selective Forwarding Unit (jvb), an XMPP server (prosody) for signalling, and a conference focus daemon (jicofo).

## Overview

This role deploys the official `jitsi/{web,prosody,jicofo,jvb}` images as a single-domain Jitsi Meet stack. Authentication is bridged to the central Keycloak via JWT (prosody validates RS256 tokens whose issuer is the realm's OIDC endpoint), and to OpenLDAP via prosody `mod_auth_ldap2` in the LDAP-only matrix variant. The web container sits behind the central openresty reverse proxy at `meet.{{ DOMAIN_PRIMARY }}`; the media plane (jvb) publishes UDP `10000/udp` on the host.

## Features

- **JWT-bridged SSO:** Prosody validates Keycloak-issued RS256 tokens via JWKS so the OIDC client controls room moderation rights.
- **LDAP direct-bind variant:** `meta/variants.yml` V3 wires prosody's `mod_auth_ldap2` against `svc-db-openldap` for a non-OIDC LDAP-only deploy.
- **Three persona surfaces:** `guest` lands on the public landing without a room, `biber` joins a JWT-issued room, `administrator` is moderator with token-gated kick/lock.
- **Self-contained Prosody:** Component secrets for jicofo, jvb, jigasi and jibri are pre-generated via `meta/secrets.yml` so XMPP auth is stable across redeploys.

## Developer Notes

Variant matrix lives in [variants.yml](./meta/variants.yml). Service flags, ports, and image pins in [services.yml](./meta/services.yml). Credentials declared in [secrets.yml](./meta/secrets.yml).

### Persona contract opt-outs

The `biber` and `administrator` Playwright personas are gated on `services.sso.enabled`. When SSO is off, [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. Two reasons:

- **V2 (no auth)**: every service is off; there is no auth chain to drive end-to-end.
- **V3 (LDAP only)**: Jitsi has no in-app HTTP OIDC adapter, so direct prosody `mod_auth_ldap2` binds happen inside the XMPP signalling layer when the user joins a room. The persona helpers only model the OIDC redirect chain through Keycloak, so the LDAP-only variant cannot be exercised via the shared persona helpers.

The `guest` persona is always live (no auth chain assumption) and the canonical-landing baseline test runs unconditionally.

## Further Resources

- [Jitsi Meet Project](https://jitsi.org/)
- [docker-jitsi-meet (upstream)](https://github.com/jitsi/docker-jitsi-meet)
- [Jitsi prosody plugins (jitsi-contrib)](https://github.com/jitsi-contrib/prosody-plugins)
