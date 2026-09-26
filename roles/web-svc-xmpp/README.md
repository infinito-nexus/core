# XMPP

## Description

[ejabberd](https://www.ejabberd.im/) is a robust, scalable, and modular XMPP server that implements the full XMPP specification plus a number of extensions (XEPs). Clients connect over TCP/TLS on ports 5222 (client-to-server) and 5269 (server-to-server), with an optional HTTP listener for the admin UI and BOSH/WebSocket bindings.

## Overview

This role deploys ejabberd on Docker Compose with the project's standard role-meta wiring. It binds ejabberd's `auth_method` to `svc-db-openldap` so XMPP clients authenticate against the project's central LDAP. The OIDC variant additionally loads `mod_oauth2_client` so a Keycloak-issued bearer token can be exchanged for an ejabberd session, but most XMPP clients still rely on SCRAM-SHA-256 over LDAP, which remains the interoperable default.

## Features

- **Containerized deployment:** Run ejabberd through Docker Compose with the project's standard role-meta wiring.
- **LDAP-backed authentication:** Authenticate XMPP clients against `svc-db-openldap` using SCRAM-SHA-256.
- **Optional OIDC bridge:** Load `mod_oauth2_client` when the OIDC variant is active, for the small set of XMPP clients that support OAuth bearer-token authentication.
- **HTTP admin and BOSH:** Expose the ejabberd web admin and BOSH/WebSocket bindings on the role's HTTP port for browser-based interaction.

## Watch Points

- Many XMPP clients do NOT support OAuth bearer-token authentication. LDAP plus SCRAM-SHA-256 is the interoperable default. If you advertise OIDC, document the small set of XMPP clients confirmed to work (Conversations, Movim, Dino) and keep LDAP plus SCRAM as the fallback path.
- ejabberd's `mod_admin` HTTP UI is the only Playwright-testable surface; XMPP client login itself runs over 5222/5269 and MUST be exercised by an XMPP-aware client outside the Playwright test loop.

## Further Resources

- [ejabberd Official Website](https://www.ejabberd.im/)
- [ejabberd Container Documentation](https://docs.ejabberd.im/CONTAINER/)
- [Converse.js](https://conversejs.org/)

## Persona contract opt-outs

ejabberd's only HTTP surface is `ejabberd_web_admin` on `/admin` (see [`templates/configuration.yml.j2`](./templates/configuration.yml.j2)). It authenticates a bare JID against LDAP over HTTP Basic, so there is no Keycloak redirect to follow and no in-app logout control to click; client authentication itself runs over ports 5222/5269 and stays outside the Playwright loop, as noted under Watch Points.
`acl.admin` additionally lists only the administrator JID, so the web admin refuses every other account outright. [`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`; the `guest` persona and the baseline reachability assertions run unconditionally.
