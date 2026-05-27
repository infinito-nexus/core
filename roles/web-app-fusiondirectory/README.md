# FusionDirectory

## Description

[FusionDirectory](https://www.fusiondirectory.org/) is a web-based LDAP administration tool that manages users, groups, and other directory objects through a pluggable interface. The application stores all of its data in an external LDAP directory, which makes it the natural front-end for the project's `svc-db-openldap` backend.

## Overview

This role deploys FusionDirectory on Docker Compose against the project's central `svc-db-openldap` server. The OIDC variant gates the FusionDirectory web UI through `web-app-oauth2-proxy` for SSO; the LDAP variant relies on the same FusionDirectory binding to `svc-db-openldap` as its primary auth path. RBAC follows the LDAP group model that FusionDirectory already understands natively, so no glue layer is required for authorisation mapping.

## Features

- **LDAP-native administration:** Manage users, groups, and posix attributes directly against `svc-db-openldap`.
- **Containerized deployment:** Run FusionDirectory through Docker Compose with the project's standard role-meta wiring.
- **Native OIDC SSO via oauth2-proxy:** Gate the FusionDirectory web UI through the project's oauth2-proxy sidecar for OIDC-authenticated entry.
- **Front-proxy integration:** Publish the app through `sys-stk-front-proxy` for TLS termination and per-domain routing.

## Further Resources

- [FusionDirectory Official Website](https://www.fusiondirectory.org/)
- [FusionDirectory Docker Image (nfrastack/fusiondirectory)](https://hub.docker.com/r/nfrastack/fusiondirectory)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
