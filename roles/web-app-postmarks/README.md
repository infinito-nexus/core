# Postmarks

## Description

Run **Postmarks**, a single-user [ActivityPub](https://www.w3.org/TR/activitypub/) bookmarking website for the Fediverse, via Docker Compose. The owner curates a public collection of bookmarks that federates to followers on Mastodon and other ActivityPub servers. Upstream project: [ckolderup/postmarks](https://github.com/ckolderup/postmarks).

## Overview

This role builds Postmarks from source into a custom image, wires it to the standard reverse proxy, and persists its SQLite data. Postmarks is single-user: there are no accounts, only "the owner". The upstream login is a single shared-secret password form that flips one session boolean (`req.session.loggedIn`).

## Features

- **Containerized build:** Clones the pinned upstream ref and runs `node server.js` behind the front proxy.
- **Single-owner model:** One privileged identity, gated by `req.session.loggedIn`.
- **Trusted-header SSO bridge:** Establishes the owner session from the oauth2-proxy identity (see below).
- **Minimal footprint:** Small Node.js/Express service that fits neatly into larger stacks.

## Single sign-on

Postmarks has no native OIDC/SAML/LDAP/REMOTE_USER login — the only auth path is the `ADMIN_KEY` password form. Under the `oauth2` SSO flavor this role adds a **trusted-header SSO bridge**:

- A sidecar `web-app-keycloak` oauth2-proxy authenticates the visitor against Keycloak (OIDC, or LDAP federated through Keycloak) and nginx overwrites the `X-Forwarded-*` identity headers on every proxied request.
- A small Express middleware (`files/sso/header_auth.js`, mounted into `server.js` at build time by `files/sso/patch_server.js`) reads only those nginx-overwritten `X-Forwarded-*` headers and flips `req.session.loggedIn = true`, so the existing `isAuthenticated` gate on `/admin` opens for the proxied owner.
- The bridge activates only when `PROXY_HEADER_SSO` is truthy (derived from `lookup('sso', application_id, 'is_proxy_gated')`); otherwise the middleware is a transparent pass-through and the native password form still guards `/admin`.
- An optional `PROXY_HEADER_SSO_ADMIN_GROUP` check against `X-Forwarded-Groups` restricts the owner session to members of the application's administrator RBAC group.

Security: the identity headers are trusted unconditionally, which is only safe because the app port is bound to `127.0.0.1` and every request traverses the oauth2-proxy that overwrites `X-Forwarded-*`. The `X-Auth-Request-*` / `Remote-User` variants are deliberately ignored so an already-authenticated client cannot inject a different identity. Logout must go through `web-svc-logout` / the oauth2-proxy sign-out, not Postmarks' own logout link, because the proxy header re-establishes the session on the next request.

RBAC is not feasible beyond the group gate: Postmarks has no in-app authorisation tier beyond "owner or not" and no per-user identity, so `X-Forwarded-Email`/`X-Forwarded-Preferred-Username` cannot scope anything inside the app. This RBAC exception is documented per [lifecycle.md](../../docs/contributing/design/role/services/lifecycle.md).

## Further Resources

- [Postmarks (GitHub)](https://github.com/ckolderup/postmarks)
- [ActivityPub (W3C Recommendation)](https://www.w3.org/TR/activitypub/)

## Persona contract opt-outs

The persona flags are declared in [templates/playwright.env.j2](./templates/playwright.env.j2). `administrator` is blocked only in the `sso: false` variants: as described above, Postmarks' sole native credential is the single shared `ADMIN_KEY` password form, which is not the Keycloak administrator secret the persona types, so without the trusted-header bridge there is no admin login to drive. `biber` is blocked in every variant — the oauth2-proxy admits only the application's administrator RBAC group and the bridge re-checks `X-Forwarded-Groups`, so `biber` is denied before Postmarks is reached, and with SSO off the only credential left belongs to no user account.
