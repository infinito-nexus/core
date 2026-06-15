# Baserow

## Description

Empower your data management with Baserow, an innovative platform that makes building and managing databases both fun and efficient. Enjoy a dynamic interface, seamless collaboration, and energetic tools that supercharge your workflow.

## Overview

This role deploys Baserow using Docker Compose, integrating key components such as PostgreSQL for the database, Redis for caching, and NGINX for secure domain management and certificate handling. It is designed to offer a robust, scalable solution for running your own Baserow instance in a containerized environment.

## Features

- **Intuitive Database Management:** Easily build, manage, and interact with your databases through a user-friendly interface.
- **Seamless Collaboration:** Collaborate in real time with team members, ensuring smooth data sharing and project management.
- **Dynamic Customization:** Adapt workflows and database structures to suit your specific needs.
- **Scalable Architecture:** Efficiently handle increasing workloads while maintaining high performance.
- **Robust API Integration:** Leverage a comprehensive API to extend functionalities and integrate with other systems.

## Further Resources

- [Baserow Homepage](https://baserow.io/)
- [Enable Single Sign-On (SSO)](https://baserow.io/user-docs/enable-single-sign-on-sso)

## SSO

The official Baserow SSO feature is Enterprise-only. This role instead gates the
community image with the shared Keycloak oauth2-proxy and installs a small
trusted-header bridge in the Baserow backend. The bridge trusts the identity
headers injected by nginx after oauth2-proxy authentication and converts them
into native Baserow JWT refresh/access tokens for the frontend.

Directory-backed identities are handled before they reach this role: Keycloak
can federate external user stores and then expose the result to Baserow via OIDC.

## Bootstrap Admin (Django Superuser)

This role can optionally bootstrap a Django superuser inside the Baserow container (useful for initial setup and automation).

- The user is created idempotently (safe to run multiple times).
- The password is passed via environment variables (robust with special characters).
- Note: Django superuser enables access to `/admin`. Workspace permissions inside Baserow still need to be configured in Baserow UI/API.

Configuration is controlled via `applications.<app>.bootstrap_admin.*`:

- `enabled` (bool)
- `username`
- `email`
- `password` (should come from vault/credentials)

## Security: SECRET_KEY

Baserow requires Django `SECRET_KEY` for correct backend operation (e.g., JWT, sessions).
This role reads it from `credentials.secret_key` and writes it into the container environment file.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
