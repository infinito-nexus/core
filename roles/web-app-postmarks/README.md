# Postmarks

## Description

Run **Postmarks**, a small mail-service client, via Docker Compose; it serves as a utility component for apps that need SMTP interactions in your stack.

## Overview

This role installs and configures the Postmarks client container with basic domain wiring. It is designed to run behind your standard reverse proxy and to interoperate with other applications that rely on SMTP functionality.

## Features

- **Containerized Client:** Simple Docker Compose deployment for the Postmarks tool.
- **SMTP-Oriented Usage:** Suited for scenarios where applications need to interact with a mail service.
- **Minimal Footprint:** Small, focused utility component that fits neatly into larger stacks.
- **Desktop Integration Hooks:** This README ensures the role is discoverable in your Web App Desktop.

## Single sign-on

OIDC is wired in via a sidecar `web-app-oauth2-proxy` in front of the Postmarks web UI; authenticated users are mapped by email or `sub` claim.
LDAP uses the same oauth2-proxy path with an LDAP backend.

RBAC is not feasible: Postmarks has no in-app authorisation tier beyond "logged in or not".
When multi-tier authorisation is needed, gate at the oauth2-proxy level.
This RBAC exception is documented per [lifecycle.md](../../docs/contributing/design/role/services/lifecycle.md).

## Further Resources

- [Postmarks (GitHub)](https://github.com/ckolderup/postmarks)
- [Simple Mail Transfer Protocol (RFC 5321)](https://www.rfc-editor.org/rfc/rfc5321)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
