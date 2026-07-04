# Jellyfin

## Description

[Jellyfin](https://jellyfin.org) is a free, open-source media server. This role deploys the official `jellyfin/jellyfin` container behind the Infinito.Nexus reverse proxy, with Keycloak OIDC (web) and central LDAP authentication provisioned via the Jellyfin auth plugins.

## Overview

Jellyfin stores its metadata in internal SQLite under `/config` — it needs **no external database**. The role persists three named volumes: `/config`, `/cache`, and `/media`. Media libraries are added in-app against `/media`.

## Features

- **Open-source media streaming** — movies, shows, music, live TV from the official Jellyfin server.
- **Keycloak OIDC (web)** — one-click web sign-in via the [`jellyfin-plugin-sso`](https://github.com/9p4/jellyfin-plugin-sso) plugin against the platform Keycloak.
- **Central LDAP (all clients)** — the [`jellyfin-plugin-ldapauth`](https://github.com/jellyfin/jellyfin-plugin-ldapauth) plugin authenticates web AND native apps against the platform OpenLDAP.
- **Break-glass admin** — a local administrator seeded via the first-run wizard (`/Startup`), independent of SSO/LDAP.
- **No external database** — self-contained SQLite under `/config`.

## Authentication & admin model

Jellyfin has **no native OIDC/LDAP**; auth is plugin-based with an important client-coverage caveat:

- **LDAP plugin** works on **every client** (web + native Android/iOS/TV/desktop apps).
- **OIDC SSO plugin** is **web-UI only** — native apps cannot use it (they sign in via LDAP/local).

`files/configure-auth.sh` (run on the deploy host) completes the first-run wizard (seeds the break-glass admin), installs both plugins via Jellyfin's own `/Packages` installer, writes the plugin configs, and restarts.

> **Validation caveat:** the plugin config is written from upstream-verified schemas, but the SSO plugin's `OidConfigs` is a `SerializableDictionary` whose exact XML shape, plus the plugin ABI compatibility with the pinned Jellyfin version, **must be confirmed on the first live deploy**. Each config file is XML-well-formedness checked before the reload.

## Further Resources

- [Jellyfin website](https://jellyfin.org)
- [Container installation](https://jellyfin.org/docs/general/installation/container/)
- [LDAP plugin](https://github.com/jellyfin/jellyfin-plugin-ldapauth)
- [SSO/OIDC plugin](https://github.com/9p4/jellyfin-plugin-sso)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
