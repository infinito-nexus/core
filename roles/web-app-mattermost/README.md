# Mattermost

## Description

Deploys [Mattermost Team Edition](https://mattermost.com/) (an open-source, self-hosted team messaging platform) as part of the Infinito.Nexus stack.

## Overview

This role unite your team with Mattermost, an open-source, self-hosted messaging platform that delivers secure, real-time collaboration through channels, threads, and integrations, keeping your conversations private and under your control.

## Features

- Single-container deployment via Docker Compose
- PostgreSQL database (MySQL/MariaDB not supported since Mattermost v8+)
- SSO via Keycloak using the GitLab OAuth2 provider (see note below)
- Email notifications via Mailu (optional)
- Persistent storage for config, data, logs, and plugins
- Accessible at `https://mattermost.<your-domain>`

## SSO / Authentication

Mattermost **Team Edition** does not support native OIDC (`MM_OPENIDSETTINGS_*`) or LDAP, since both are Enterprise-only features.

The workaround used here is the **GitLab OAuth2 provider** (`MM_GITLABSETTINGS_*`), which is generic enough to work with any OIDC-compatible identity provider including Keycloak. This provides true SSO: user accounts are automatically created in Mattermost on first login.

The login button in the UI will read "SSO with Infinito.Nexus" (renamed via injected JavaScript). The underlying auth flow is standard OAuth2/OIDC against Keycloak.

To enable SSO, set `services.oidc.enabled: true` (the default) in your inventory and ensure `OIDC.CLIENT.SECRET` is configured.

## Configuration

Key settings in `meta/services.yml` and `meta/server.yml`:

| Key | Default | Description |
|-----|---------|-------------|
| `services.oidc.enabled` | `true` | Enable Keycloak SSO via GitLab OAuth2 |
| `services.postgres.shared` | `true` | Use the shared PostgreSQL service instead of a role-local one |
| `services.mattermost.version` | `latest` | Docker image tag |
| `server.domains.canonical` | `mattermost.{{ DOMAIN_PRIMARY }}` | Public domain |

## References

- [Mattermost Docker Install](https://docs.mattermost.com/install/install-docker.html)
- [Mattermost Configuration Settings](https://docs.mattermost.com/configure/configuration-settings.html)
- [GitLab SSO in Mattermost](https://docs.mattermost.com/deployment/sso-gitlab.html)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
