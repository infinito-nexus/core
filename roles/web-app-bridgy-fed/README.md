# Bridgy Fed

## Description

[Bridgy Fed](https://fed.brid.gy/) is a federation bridge between ActivityPub (the Fediverse), the AT Protocol (Bluesky), and the IndieWeb (webmentions and microformats2). It mirrors identities and cross-network interactions so a post on one network reaches followers on the others.

## Overview

This role builds and runs Bridgy Fed as a Docker container behind the project's front-proxy. An optional Firestore-emulator sidecar in Datastore mode provides the storage backend for non-production deployments.

## Features

- **Cross-network federation:** Mirror posts and interactions between ActivityPub, AT Protocol, and the IndieWeb.
- **Containerized deployment:** Run the upstream Flask app under gunicorn through Docker Compose.
- **Front-proxy integration:** Publish the app through `sys-stk-front-proxy` for TLS termination and per-domain routing.
- **Optional Firestore emulator:** Use the Datastore-mode emulator sidecar for non-production deployments.

## Single Sign-On

This role does NOT configure OIDC against `web-app-keycloak`, LDAP against `svc-db-openldap`, or any role-claim / LDAP-group RBAC mapping. Bridgy Fed authenticates users via their fediverse or atproto credentials at the source platform, not via local accounts. There is no local user table to bind an external IdP to, and no in-app authorisation tier to map a Keycloak role or LDAP group onto. Placing Bridgy Fed behind `web-app-oauth2-proxy` would break inbound federation traffic and MUST NOT be done. This SSO and RBAC exception is documented per [lifecycle.md](../../docs/contributing/design/role/services/lifecycle.md).

## Further Resources

- [Bridgy Fed Official Site](https://fed.brid.gy/)
- [Bridgy Fed Documentation](https://bridgy-fed.readthedocs.io/)
- [Bridgy Fed Source on GitHub](https://github.com/snarfed/bridgy-fed)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
