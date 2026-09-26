# FusionDirectory

## Description

[FusionDirectory](https://www.fusiondirectory.org/) is a web-based LDAP administration tool that manages users, groups, and other directory objects through a pluggable interface. The application stores all of its data in an external LDAP directory, which makes it the natural front-end for the project's `svc-db-openldap` backend.

## Overview

This role deploys FusionDirectory on Docker Compose against the project's central `svc-db-openldap` server. The OIDC variant gates the FusionDirectory web UI through `web-app-keycloak`'s SSO-proxy sidecar for SSO; the LDAP variant relies on the same FusionDirectory binding to `svc-db-openldap` as its primary auth path. RBAC follows the LDAP group model that FusionDirectory already understands natively, so no glue layer is required for authorisation mapping.

## Features

- **LDAP-native administration:** Manage users, groups, and posix attributes directly against `svc-db-openldap`.
- **Containerized deployment:** Run FusionDirectory through Docker Compose with the project's standard role-meta wiring.
- **Native OIDC SSO via SSO-proxy sidecar:** Gate the FusionDirectory web UI through the project's SSO-proxy sidecar (provided by `web-app-keycloak`) for OIDC-authenticated entry.
- **Front-proxy integration:** Publish the app through `sys-stk-front-proxy` for TLS termination and per-domain routing.

## Further Resources

- [FusionDirectory Official Website](https://www.fusiondirectory.org/)

## Persona contract opt-outs

The shared `biber` and `administrator` persona journeys are opted out via `PERSONA_BIBER_BLOCKED` / `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`.
The oauth2-proxy sidecar only gates the vhost — FusionDirectory keeps its own LDAP-bind login behind it, which the role's OIDC scenario in `files/playwright/playwright.spec.js` asserts by expecting a "Sign in" button to still be visible after the Keycloak round-trip.
`tasks/main.yml` provisions no FusionDirectory account, so the Keycloak identity maps to no directory session the shared helpers could carry through to an in-app logout.
