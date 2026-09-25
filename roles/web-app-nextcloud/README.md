# Nextcloud

## Description

Elevate your collaboration with Nextcloud, a vibrant self-hosted cloud solution designed for dynamic file sharing, seamless communication, and effortless teamwork. Nextcloud offers a full suite of integrated tools (including LDAP and OIDC authentication, Redis caching, and automated plugin management via OCC) to empower a secure, extensible, and production-ready cloud environment.

## Overview

This role provisions a complete Nextcloud deployment using Docker Compose. It automates the setup of the Nextcloud application along with its underlying MariaDB database and configures the system for secure public access via an NGINX reverse proxy. The deployment includes automated configuration merging into `config.php`, health check routines, and integrated support for backup and recovery operations.

## Features

- **Fully Dockerized Deployment:** Simplifies installation using Docker Compose for the Nextcloud application and its MariaDB backend.
- **Secure Access:** Integrates with an NGINX reverse proxy for encrypted, high-performance access.
- **Robust Authentication:** Supports LDAP and OIDC for secure identity and access management.
- **Automated Configuration Management:** Uses additive configuration files to dynamically merge system settings into `config.php`.
- **Integrated Backup & Recovery:** Provides built-in support for backup and restoration operations to safeguard your data.
- **Extensible Plugin Framework:** Easily manage and configure hundreds of Nextcloud plugins using the OCC command line tool.

## Addons

The config-bearing Nextcloud apps are declared in `meta/addons/` under the unified addon contract (requirement 026).
Each declaration carries its full `occ config:app:set` payload under `config:`.
The enable-only appstore apps stay under `nextcloud.plugins` in [`meta/services.yml`](./meta/services.yml).

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `sociallogin` | `plugin` | enabled when the SSO OIDC plugin selector picks it | `sso` → `web-app-keycloak` |
| `user_ldap` | `plugin` | enabled with the `ldap` service | `ldap` → `svc-db-openldap` |
| `bbb` | `plugin` | enabled with the `bigbluebutton` partner | `bigbluebutton` → `web-app-bigbluebutton` |
| `onlyoffice` | `plugin` | enabled with the `onlyoffice` partner | `onlyoffice` → `web-svc-onlyoffice` |
| `richdocuments` | `plugin` | enabled with the `collabora` partner | `collabora` → `web-svc-collabora` |
| `spreed` | `plugin` | enabled with the `talk` service | `talk`, `coturn` |
| `whiteboard` | `plugin` | `required` (always installed) | none (self-hosted backend) |
| `xwiki` | `plugin` | enabled with the `xwiki` partner | `xwiki` → `web-app-xwiki` |

The SSO (`sociallogin`) and LDAP (`user_ldap`) login surfaces are covered by the OIDC/LDAP Playwright specs (requirements 017/018).

## MCP Server

Nextcloud serves a Model Context Protocol endpoint through the AppAPI proxy of the `context_agent` ExApp.

| Property | Value |
|----------|-------|
| Endpoint | `/mcp` on the `contextagentmcp` adapter sidecar |
| Container-network URL | `http://contextagentmcp:8080/mcp` |
| Transport | Streamable HTTP |
| Exposure | internal (the sidecar is reachable on the container network only; the hub's own MCP route is not published to clients) |
| Auth | `credentials.mcp_bearer`, sent as `Authorization: Bearer <bearer>` |
| Identity | the Nextcloud account the app password belongs to; every tool call the adapter forwards runs with that account's permissions |
| Implementation | adapter (`svc-ai-mcp-adapter` in `mcp_passthrough` mode, fronting the `context_agent` ExApp) |
| Default state | off; `mcp.enabled` turns on when `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is deployed |

### Deployment

The `context_agent` and `contextagentmcp` services in [`meta/services.yml`](./meta/services.yml) render only while `mcp.enabled` is true. The first runs `ghcr.io/nextcloud/context_agent`, listens on its internal port for AppAPI only, and shares `credentials.context_agent_app_secret` with the ExApp registration as `APP_SECRET`. The second is the adapter sidecar, built from the staged `svc-ai-mcp-adapter` context, read-only with every capability dropped, and it is the only MCP endpoint clients are given.

The sidecar reads its upstream credential from an `upstream.env` file rather than from the compose environment, because the app password does not exist when the stack is first rendered. [`tasks/utils/mcp.yml`](./tasks/utils/mcp.yml) writes that file after the mint and recreates the sidecar through `svc-ai-mcp-adapter`'s `rebuild.yml`: `compose up` resolves `env_file` while creating the container, which a restart would not.

[`tasks/utils/mcp.yml`](./tasks/utils/mcp.yml) waits for the ExApp heartbeat, registers the deploy daemon and the ExApp (route `^/mcp`, verbs `POST,GET,DELETE`, access level `1`), enables the ExApp, mints an app password for the dedicated MCP account via `occ user:auth-tokens:add`, persists it through `sys-token-store` under `users['mcp-web-app-nextcloud'].tokens['web-app-nextcloud']`, and asserts that an authenticated `initialize` call answers `200`.

### Authorization subject

`auth_subject: service_account`: [`tasks/utils/mcp/token.yml`](./tasks/utils/mcp/token.yml) creates the account `NEXTCLOUD_MCP_USERNAME` with `occ user:add` if it is missing, mints the app password against that account, and stores it under `mcp.credential.owner`. Every call carries that account's rights, not the administrator's, no matter who asked the client. Reaching the tool server is gated on the role's `mcp` RBAC group, which is a separate grant from holding a Nextcloud account.

### Tool categories

The 2.7.0 image ships 23 tool categories, which are application names (`calendar`, `files`, `mail`, `talk`, …) rather than operations: each bundles its read and its write tools, and the hub offers no setting that removes only the mutating ones. Enabling the ExApp writes `true` for every category absent from `tool_status`, so the hub itself serves all of them, write tools included.

The adapter is what bounds that. [`files/mcp/tools.json`](./files/mcp/tools.json) names the nine read tools of `calendar`, `contacts` and `files` — the three categories whose upstream `is_available` is unconditional, so the set does not vary with which optional apps a deployment installs. `svc-ai-mcp-adapter` refuses any tool outside that list and any tool marked `mutating` while `mutating_tools_enabled` is false, and it refuses to start at all if the contract's `schema_sha256` does not match the file. The refusal happens in the sidecar, so it holds for every client regardless of what each renders locally.

The hub keeps all its categories. Nextcloud's own Assistant is unaffected by the bound: it reads the same `tool_status`, and nothing here narrows it.

The app password never reaches a client. Clients present `credentials.mcp_bearer` to the sidecar; the sidecar presents the app password upstream. Revoking one does not revoke the other.

```bash
occ app_api:app:config:get context_agent tool_status
occ app_api:app:config:set context_agent tool_status --value '<json map of category to bool>'
```

Widening the exposed set means adding the tool to `files/mcp/tools.json`, recomputing both `adapter.specification_sha256` and `tools.schema_sha256`, and listing it in `mcp.tools.allowlist`.

### Verification

The sidecar is reachable on the container network only, so a client probes it from inside the stack:

```bash
curl -i -X POST \
  -H 'Authorization: Bearer <credentials.mcp_bearer>' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"cli","version":"1"}}}' \
  http://contextagentmcp:8080/mcp
```

From outside, every MCP path answers `404`. The hub serves its route under two spellings — with and without the `/index.php` front controller — and `roles/sys-svc-proxy/templates/mcp/vhost.conf.j2` withdraws both, so neither reaches the Context Agent. [`files/playwright/test-mcp-guest.js`](./files/playwright/test-mcp-guest.js) probes all three public paths and asserts each answers `>= 300` without an MCP protocol body.

### Default state

Off. `mcp.enabled` is true only while `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is part of the deployment.

### How to disable

Remove the MCP client roles, or pin `mcp.enabled: false` for this role. The `context_agent` service is then not rendered, the ExApp is not registered with AppAPI, and no app password is minted.

## Documentation

A detailed documentation for the use and administration of Nextcloud on Infinito.Nexus you will find [here](docs/README.md).

## Further Resources

- [Nextcloud Official Website](https://nextcloud.com/)
- [Nextcloud Docker Documentation](https://github.com/nextcloud/docker)
- [Nextcloud Admin Manual](https://docs.nextcloud.com/server/latest/admin_manual/)
- [LDAP Integration Guide](https://docs.nextcloud.com/server/latest/admin_manual/configuration_user/user_auth_ldap.html)
- [OIDC Login Plugin (pulsejet)](https://github.com/pulsejet/nextcloud-oidc-login)
- [Sociallogin Plugin (Official)](https://apps.nextcloud.com/apps/sociallogin)

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). Nextcloud presents three different login surfaces depending on the variant (native, `oidc_login`, `sociallogin`), the native administrator authenticates with the role-local `credentials.administrator_password` rather than the Keycloak secret, and the `#firstrunwizard` modal intercepts the user-menu click the generic logout depends on. Both personas are therefore driven by the role's own login specs — `test-login-admin-native.js`, `test-login-admin-oidc.js`, `test-login-biber-oidc.js` and `test-login-biber-ldap.js` under `files/playwright/` — which carry the flavor switch, the modal dismissal and the login retry the shared helper lacks.
