# XMPP

## Description

[ejabberd](https://www.ejabberd.im/) is a robust, scalable, and modular XMPP server that implements the full XMPP specification plus a number of extensions (XEPs). Clients connect over TCP/TLS on ports 5222 (client-to-server) and 5269 (server-to-server), with an optional HTTP listener for the admin UI and BOSH/WebSocket bindings.

## Overview

This role deploys ejabberd on Docker Compose with the project's standard role-meta wiring. It binds ejabberd's `auth_method` to `svc-db-openldap` so XMPP clients authenticate against the project's central LDAP. ejabberd has no OIDC client, so the role declares no `sso` service and LDAP is its only sign-in path.

## Features

- **Containerized deployment:** Run ejabberd through Docker Compose with the project's standard role-meta wiring.
- **LDAP-backed authentication:** Authenticate XMPP clients against `svc-db-openldap`.
- **LDAP vCards:** With LDAP enabled, `mod_vcard` reads every vCard from the directory: `FN`, `GIVEN`, `FAMILY`, `EMAIL`, `NICKNAME`, `TEL` and `PHOTO` come from the matching `LDAP.USER.ATTRIBUTES`. Users cannot edit them in their client.
- **Server administrators:** `acl.admin` lists the platform administrator and every member of the `web-svc-xmpp` `administrator` role, resolved at deploy time. The `configure` and `announce` access rules grant the web admin and announcements to that ACL.
- **HTTP admin and BOSH:** Expose the ejabberd web admin and BOSH/WebSocket bindings on the role's HTTP port for browser-based interaction.

## Watch Points

- ejabberd's `mod_admin` HTTP UI is the only Playwright-testable surface; XMPP client login itself runs over 5222/5269 and MUST be exercised by an XMPP-aware client outside the Playwright test loop.

## Further Resources

- [ejabberd Official Website](https://www.ejabberd.im/)
- [ejabberd Container Documentation](https://docs.ejabberd.im/CONTAINER/)
- [Converse.js](https://conversejs.org/)

## Persona contract opt-outs

ejabberd's only HTTP surface is `ejabberd_web_admin` on `/admin` (see [`templates/configuration.yml.j2`](./templates/configuration.yml.j2)). It authenticates a bare JID against LDAP over HTTP Basic, so there is no Keycloak redirect to follow and no in-app logout control to click; client authentication itself runs over ports 5222/5269 and stays outside the Playwright loop, as noted under Watch Points.
`acl.admin` lists only the platform administrator and the members of the `administrator` role, so the web admin refuses every other account outright. [`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`; the `guest` persona and the baseline reachability assertions run unconditionally.
