# Jellyfin

## Description

[Jellyfin](https://jellyfin.org) is a free, open-source media server. This role deploys the official `jellyfin/jellyfin` container behind the Infinito.Nexus reverse proxy, with Keycloak OIDC (web) and central LDAP authentication provisioned via the Jellyfin auth plugins.

## Overview

Jellyfin stores its metadata in internal SQLite under `/config` - it needs **no external database**. The role persists three named volumes: `/config`, `/cache`, and `/media`. Media libraries are added in-app against `/media`.

## Features

- **Open-source media streaming** - movies, shows, music, live TV from the official Jellyfin server.
- **Keycloak OIDC (web)** - one-click web sign-in via the [`jellyfin-plugin-sso`](https://github.com/9p4/jellyfin-plugin-sso) plugin against the platform Keycloak.
- **Central LDAP (all clients)** - the [`jellyfin-plugin-ldapauth`](https://github.com/jellyfin/jellyfin-plugin-ldapauth) plugin authenticates web AND native apps against the platform OpenLDAP.
- **Break-glass admin** - a local administrator seeded via the first-run wizard (`/Startup`), independent of SSO/LDAP.
- **Login methods:** `services.jellyfin.login.method` declares `sso`, `ldap` and `native`. Jellyfin has no setting that hides its own sign-in form, so [files/shell/configure-auth.sh](./files/shell/configure-auth.sh) writes the sign-in page through the server branding: `sso` puts the "Sign in with Keycloak" button into the login disclaimer, and with `ldap` and `native` both off the custom CSS hides the password form, the user picker, "Manual Login", "Quick Connect" and "Forgot Password". Local and LDAP accounts share one form (shared form), so `native: false` in LDAP mode cannot keep other local accounts out. Jellyfin has no second factor, passkey or self-registration of its own. The CSS only shapes the web client: native Jellyfin apps keep their own sign-in screen, which the LDAP plugin and local accounts answer.
- **Break-glass path:** the local administrator signs in through `POST /Users/AuthenticateByName` of the Jellyfin API or through any native Jellyfin app with its local password, whatever the web sign-in page shows; the Playwright helper `signInViaBreakGlass` hands such an API session to the web client.
- **Administrator role from the IdP:** every realm user may sign in; members of the `administrator` RBAC group of `web-app-jellyfin` get the Jellyfin administrator flag. The SSO plugin reads it from the `groups` claim, the LDAP plugin from the `memberOf` entry of the group, and both remove the flag at the next login of a user who left the group.
- **LDAP profile image:** an account the LDAP plugin creates takes the directory photo (`jpegPhoto`) as its avatar, and [files/python/photo_sync.py](./files/python/photo_sync.py) pushes a changed photo to the existing account as a host hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer.
- **No external database** - self-contained SQLite under `/config`.
- **CPU transcoding** - the container gets no GPU device, so Jellyfin transcodes in software on the CPU.

## Authentication & Admin Model

Jellyfin has **no native OIDC/LDAP**; auth is plugin-based with an important client-coverage caveat:

- **LDAP plugin** works on **every client** (web + native Android/iOS/TV/desktop apps).
- **OIDC SSO plugin** is **web-UI only** - native apps cannot use it (they sign in via LDAP/local).

`files/configure-auth.sh` (run on the deploy host) completes the first-run wizard (seeds the break-glass admin), installs both plugins via Jellyfin's own `/Packages` installer, writes the plugin configs, and restarts.

## Further Resources

- [Jellyfin website](https://jellyfin.org)
- [Container installation](https://jellyfin.org/docs/general/installation/container/)
- [LDAP plugin](https://github.com/jellyfin/jellyfin-plugin-ldapauth)
- [SSO/OIDC plugin](https://github.com/9p4/jellyfin-plugin-sso)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/Q1AHrVLgKVPErMC2BH4hU4)

## Persona contract opt-outs

The shared `biber` persona journey is opted out via `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2`.
A Jellyfin account binds to exactly one authentication provider, so biber's login is owned by the per-addon specs that know which provider is live: `files/playwright/addons/sso-authentication.spec.js` for OIDC and `addons/ldap-authentication.spec.js` for the LDAP-only matrix variant.
The generic persona cannot pick between them and would duplicate or contradict that coverage; `playwright.spec.js` keeps the `guest` scenario and the native administrator login.
