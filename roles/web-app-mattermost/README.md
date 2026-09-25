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

To enable SSO, set `services.sso.enabled: true` (the default) in your inventory and ensure `OIDC.CLIENT.SECRET` is configured.

## MCP Server

Mattermost exposes a Model Context Protocol server through the prepackaged Agents plugin (`mattermost-ai`), which ships inside the pinned `mattermost/mattermost-team-edition` image.

| Property | Value |
|----------|-------|
| Endpoint | `/mcp` on the `mattermostmcp` sidecar; the adapter reaches `/plugins/mattermost-ai/mcp-server/mcp` on the `mattermost` service upstream |
| Health path | `/plugins/mattermost-ai/mcp-server/.well-known/oauth-protected-resource` |
| Transport | `streamable_http` (stateless); SSE is not served |
| Auth | `Authorization: Bearer <personal access token>` |
| Subject | The token owner; tool calls run with that account's Mattermost permissions |
| Exposure | `internal` |

### Default state

`mcp.enabled` resolves to `true` only when `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is part of the same deployment, and is `false` otherwise. While it is `true` the deploy:

- sets `MM_SERVICESETTINGS_ENABLEUSERACCESSTOKENS=true`,
- enables the `mattermost-ai` plugin through `mmctl --local`,
- sets `mcp.enablePluginServer` in the plugin's active `agents_confighistory` row and reloads the plugin,
- mints a personal access token for the administrator account and persists it with `sys-token-store` under `users.administrator.tokens['web-app-mattermost']`.

While it is `false` the route is not registered and the endpoint answers `404`. Unauthenticated requests to the enabled endpoint answer `401` with a `WWW-Authenticate: Bearer resource_metadata="<health path URL>"` header.

### Authorization subject

`auth_subject: administrator`: Mattermost bounds a call by the account the token
belongs to. This deployment mints that personal access token for the
administrator account, so calls arrive with that account's rights whoever asked.
Reaching the tool server is gated on the role's `mcp` RBAC group.

### Tool categories

The endpoint serves the Agents plugin's native Mattermost tool catalog:

- channels: list, read, create, update, archive,
- posts: search, read, create, update, delete,
- direct messages: read and send,
- users and teams: look up, add members, update profiles,
- files: list, read, upload.

The catalog includes mutating entries (`create`, `update`, `archive`, `delete`,
`send`, `upload`). The Agents plugin exposes no filter, scope or permission flag
that removes them, so `mcp.tools.mutating_tools_enabled: false` records
the deployment's intent rather than an enforced state. Every call is bounded by
the permissions of the account the bearer token belongs to, which here is the
administrator.

### How to disable

Remove the MCP client roles, or pin `mcp.enabled: false` for this role. The Agents plugin's MCP server is then left switched off and no personal access token is issued.

## Configuration

Key settings in `meta/services.yml` and `meta/server.yml`:

| Key | Default | Description |
|-----|---------|-------------|
| `services.sso.enabled` | `true` | Enable Keycloak SSO via GitLab OAuth2 |
| `services.postgres.shared` | `true` | Use the shared PostgreSQL service instead of a role-local one |
| `services.mattermost.version` | `latest` | Docker image tag |
| `domains.canonical` | `mattermost.{{ DOMAIN_PRIMARY }}` | Public domain |

## Addons

This role declares no addons (it ships no `meta/addons/` directory). Mattermost **Team Edition** manages plugin install and enablement at runtime; there is no declarative per-plugin install path in this role. Plugins are operator-managed. The named volumes `plugins` and `client-plugins` declared in `meta/volumes.yml` are node-local derived copies that every replica extracts for itself from the image's prepackaged bundles; an uploaded bundle persists in the file store, not in them. No addon bridges any in-repo service.

## References

- [Mattermost Docker Install](https://docs.mattermost.com/deployment-guide/server/deploy-containers.html)
- [Mattermost Configuration Settings](https://docs.mattermost.com/administration-guide/configure/configuration-settings.html)
- [GitLab SSO in Mattermost](https://docs.mattermost.com/administration-guide/onboard/sso-gitlab.html)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2` for the same mechanism. Mattermost Team Edition ships no native OIDC provider, so the role piggybacks Keycloak onto the GitLab OAuth slot (`MM_GITLABSETTINGS_*` in `templates/env.j2`); the resulting entry point is `a[href='/oauth/gitlab/login']`, relabelled "SSO with Infinito.Nexus" by `templates/javascript.js.j2`, which the shared helper's name-based login matcher does not recognise. Mattermost v11+ also serves a `/landing` interstitial to unauthenticated visitors that only clears once `localStorage.__landingPageSeen__` is seeded before navigation, and the shared helper has no init-script hook to do that.

The journey is covered bespoke in `files/playwright/test-sso-login.js`, which seeds the landing flag, clicks the GitLab-slot link, verifies the channel view, and signs out via `/logout`; `files/playwright/test-biber-dm-administrator.js` adds the peer exchange. The path back to the generic personas is an SSO control whose accessible name matches the shared matcher.
