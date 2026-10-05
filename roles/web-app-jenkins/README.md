# Jenkins

## Description

[Jenkins](https://www.jenkins.io/) is an open-source automation server that orchestrates the build, test, and deployment of software through pipelines, freestyle jobs, and a large plugin ecosystem.

## Overview

This role deploys Jenkins on Docker Compose. It builds a custom Jenkins image that pre-installs the `ldap`, `role-strategy`, and `configuration-as-code` plugins plus every plugin its enabled addons declare, then mounts a JCasC YAML file that wires the security realm against Keycloak (variant 0, OIDC) or `svc-db-openldap` (variant 1, LDAP). The setup wizard is skipped via `JAVA_OPTS=-Djenkins.install.runSetupWizard=false` so the JCasC config takes over from first boot.

## Features

- **Containerized deployment:** Run Jenkins through Docker Compose with the role-specific custom image.
- **Native OIDC SSO:** Authenticate users against Keycloak via the `oic-auth` plugin, configured by JCasC at boot.
- **LDAP variant:** Switch to Jenkins's core `ldap` plugin via the role's matrix-deploy variant 1 against `svc-db-openldap`.
- **Role-strategy authorisation:** Map Keycloak groups and LDAP groups onto Jenkins authorities through the `role-strategy` plugin.
- **JCasC-managed configuration:** Persist the security realm and authorisation strategy as code via Configuration as Code.
- **Pre-installed plugin set:** Bake build-pipeline, credentials, and SCM plugins into the image so first start-up does not block on plugin downloads.
- **MCP server surface:** Serve the `mcp-server` plugin's streamable-HTTP endpoint on the container network, guarded by an administrator API token and limited to the read-only tool default.

## MCP Server

The role exposes Jenkins as an MCP server through the [MCP Server plugin](https://plugins.jenkins.io/mcp-server/), baked into the image alongside the other plugins in `templates/plugins.txt.j2`. The surface is declared as the `mcp` service in `meta/services.yml`.

| Property | Value |
| --- | --- |
| Transport | `streamable_http` |
| Plugin | `mcp-server` pinned to `0.190.ve5a_6581ffc96` in [`templates/plugins.txt.j2`](./templates/plugins.txt.j2) |
| Endpoint | `http://jenkins:8080/mcp-server/mcp` |
| Health | `/mcp-health` |
| Auth | `basic_auth` (`Authorization: Basic base64(<user>:<apiToken>)`) |
| Subject | administrator |
| Tools | read-only by default, mutating tools off |

Enable the surface by deploying `web-app-hermes` or `web-app-openclaw` alongside Jenkins, or by forcing `mcp.enabled` on. Open WebUI skips the server because it cannot present basic auth.

At boot, `files/mcp-api-token.groovy` runs from `init.groovy.d` and mints an API token named `infinito-mcp` for the administrator account, writing the plain value to `/var/jenkins_home/secrets/infinito-mcp.token`. `tasks/utils/mcp.yml` then reads that value out of the container, persists it through `sys-token-store`, and hard-fails the deploy when the controller rejects it. `MCP_DISCOVERED_SERVERS` picks the token up from the store and the client roles build the header via the `mcp_authorization` filter.

Reach the endpoint by hand with:

```bash
curl -u "<administrator>:<apiToken>" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data-binary '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"cli","version":"1.0.0"}}}' \
  http://jenkins:8080/mcp-server/mcp
```

### Default state

Off. `mcp.enabled` is true only while `web-app-hermes` or
`web-app-openclaw` is part of the deployment.

### Authorization subject

`auth_subject: administrator`: the API token is issued against the
administrator account, so every call carries that account's rights no matter who
asked the client. Reaching the tool server is gated on the role's `mcp` RBAC
group, which is a separate grant from administering Jenkins.

### Tool scope

The plugin answers `initialize` without credentials, because that call is
capability negotiation and carries no data. Everything after it is guarded: an
unauthenticated `tools/list` is refused and returns no tool inventory.

### How to disable

Remove the MCP client roles, or pin `mcp.enabled: false` for this role.
The MCP Server plugin is then not installed and the boot hook mints no API token.

## Addons

Plugins are declared in `meta/addons/` under the unified addon contract. `templates/plugins.txt.j2` renders one `config.plugin_id` line per enabled addon on top of the role's base plugin set, and `jenkins-plugin-cli` installs the result while the custom image builds:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `oic-auth` | `plugin` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `prometheus` | `plugin` | enabled whenever the `prometheus` service is present (`web-app-prometheus` co-deployed) | `prometheus` → `web-app-prometheus` |
| `gitea` | `plugin` | enabled whenever the `gitea` service is present (`web-app-gitea` co-deployed) | `gitea` → `web-app-gitea` |
| `gitlab-plugin` | `plugin` | enabled whenever the `gitlab` service is present (`web-app-gitlab` co-deployed) | `gitlab` → `web-app-gitlab` |
| `mattermost` | `plugin` | enabled whenever the `mattermost` service is present (`web-app-mattermost` co-deployed) | `mattermost` → `web-app-mattermost` |

`oic-auth` is configured by `templates/casc.yaml.j2`, which selects the `oic` security realm on the same `services.sso.enabled` flag the addon reads. `prometheus` serves `config.metrics_path` from first boot without further configuration. The `gitea`, `gitlab-plugin`, and `mattermost` SCM/notifier connections each need a partner-side API token or incoming webhook, so the role installs the plugin and publishes the partner URL under `config.server_url` while the connection itself is entered by the operator.

## Further Resources

- [Jenkins Official Website](https://www.jenkins.io/)
- [Jenkins oic-auth plugin](https://plugins.jenkins.io/oic-auth/)
- [Jenkins Configuration as Code plugin](https://plugins.jenkins.io/configuration-as-code/)
- [Jenkins MCP Server plugin](https://plugins.jenkins.io/mcp-server/)

## Persona contract opt-outs

The shared `biber` and `administrator` persona journeys are opted out via `PERSONA_BIBER_BLOCKED` / `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`.
Outside the OIDC variant, `templates/casc.yaml.j2` selects the `ldap` or `local` security realm and Jenkins' only login surface is its own Java-realm form, whose fields are named `j_username` / `j_password` (pinned by the LDAP scenario in `files/playwright/playwright.spec.js`) — names the shared native-login probe does not match, so the persona never authenticates.
The flag is currently unconditional; narrowing it to `{% if not JENKINS_OIDC_ENABLED %}` once the OIDC persona journey has been verified end-to-end is the path back.
