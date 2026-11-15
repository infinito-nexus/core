# Jenkins

## Description

[Jenkins](https://www.jenkins.io/) is an open-source automation server that orchestrates the build, test, and deployment of software through pipelines, freestyle jobs, and a large plugin ecosystem.

## Overview

This role deploys Jenkins on Docker Compose. It builds a custom Jenkins image that pre-installs the `ldap`, `role-strategy`, and `configuration-as-code` plugins plus every plugin its enabled addons declare, then mounts a JCasC YAML file that wires the security realm against Keycloak (variant 0, OIDC) or `svc-db-openldap` (variant 1, LDAP). The setup wizard is skipped via `JAVA_OPTS=-Djenkins.install.runSetupWizard=false` so the JCasC config takes over from first boot.

## Features

- **Containerized deployment:** Run Jenkins through Docker Compose with the role-specific custom image.
- **Native OIDC SSO:** Authenticate users against Keycloak via the `oic-auth` plugin, configured by JCasC at boot.
- **LDAP variant:** Switch to Jenkins's core `ldap` plugin via the role's matrix-deploy variant 1 against `svc-db-openldap`.
- **Login methods:** `services.jenkins.login.method` declares `sso`, `ldap`, `native` and `registration` (see [Login Methods](../../docs/contributing/design/iam/login.md)). Jenkins runs one security realm, so [`templates/casc.yaml.j2`](./templates/casc.yaml.j2) maps them onto it: the `oic` realm while `sso` is on, else the `ldap` realm while `ldap` is on, else the `local` realm, which seeds the platform administrator while `native` is on and sets `allowsSignup` from `registration`. Jenkins core has no second factor, so the role declares no `2fa`.
- **Break-glass access:** with the `oic` realm, `/login` always hands over to Keycloak and Jenkins renders no local form. The break-glass runs on the host: override `services.jenkins.login.method.sso.enabled: false` in the inventory and redeploy, which renders the `ldap` or `local` realm, or, when no deploy can run, replace the `securityRealm` block of the mounted `casc.yaml` in the role's instance directory with the `local` realm of the platform administrator and restart the container, since JCasC applies the file at startup. The API token [`files/mcp-api-token.groovy`](./files/mcp-api-token.groovy) mints belongs to the MCP credential owner, not to an administrator, so it is no break-glass.
- **Role-strategy authorisation:** Map the RBAC groups of `meta/rbac.yml` onto the global roles `admin` (`administrator`), `developer` (create, configure, build and delete jobs) and `viewer` (read jobs and builds) through the `role-strategy` plugin. The OIDC realm matches the group paths of the groups claim, the LDAP realm matches the `web-app-jenkins-<role>` group names under the roles OU. A signed-in account without one of these groups is refused.
- **Profile sync:** Take the full name and email from the OIDC claims on every login, or from the directory's full name and mail attributes in the LDAP variant.
- **JCasC-managed configuration:** Persist the security realm and authorisation strategy as code via Configuration as Code.
- **Pre-installed plugin set:** Bake build-pipeline, credentials, and SCM plugins into the image so first start-up does not block on plugin downloads.
- **MCP server surface:** Serve the `mcp-server` plugin's streamable-HTTP endpoint on the container network, guarded by a service-account API token and limited to the read-only tool default.

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

`auth_subject: service_account`: the API token is issued against the MCP
credential owner, so every call carries that account's rights no matter who
asked the client. `templates/casc.yaml.j2` grants that account the `viewer`
role, or the `developer` role while `mcp.tools.mutating_tools_enabled` is on. Reaching the tool server is gated on the role's `mcp` RBAC
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
| `oic-auth` | `plugin` | enabled with the `sso` login method, which is on whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `prometheus` | `plugin` | enabled whenever the `prometheus` service is present (`web-app-prometheus` co-deployed) | `prometheus` → `web-app-prometheus` |
| `gitea` | `plugin` | enabled whenever the `gitea` service is present (`web-app-gitea` co-deployed) | `gitea` → `web-app-gitea` |
| `gitlab-plugin` | `plugin` | enabled whenever the `gitlab` service is present (`web-app-gitlab` co-deployed) | `gitlab` → `web-app-gitlab` |
| `mattermost` | `plugin` | enabled whenever the `mattermost` service is present (`web-app-mattermost` co-deployed) | `mattermost` → `web-app-mattermost` |

`oic-auth` is configured by `templates/casc.yaml.j2`, which selects the `oic` security realm on the same `services.jenkins.login.method.sso.enabled` flag the addon reads. `prometheus` serves `config.metrics_path` from first boot without further configuration. The `gitea`, `gitlab-plugin`, and `mattermost` SCM/notifier connections each need a partner-side API token or incoming webhook, so the role installs the plugin and publishes the partner URL under `config.server_url` while the connection itself is entered by the operator.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Jenkins Official Website](https://www.jenkins.io/)
- [Jenkins oic-auth plugin](https://plugins.jenkins.io/oic-auth/)
- [Jenkins Configuration as Code plugin](https://plugins.jenkins.io/configuration-as-code/)
- [Jenkins MCP Server plugin](https://plugins.jenkins.io/mcp-server/)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/DPv6fGim13i7WdAb98pL1h)

## Persona contract opt-outs

The shared `biber` and `administrator` persona journeys are opted out via `PERSONA_BIBER_BLOCKED` / `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`.
Outside the OIDC variant, `templates/casc.yaml.j2` selects the `ldap` or `local` security realm and Jenkins' only login surface is its own Java-realm form, whose fields are named `j_username` / `j_password` (pinned by the LDAP scenario in `files/playwright/playwright.spec.js`) — names the shared native-login probe does not match, so the persona never authenticates.
The flag is currently unconditional; narrowing it to `{% if not JENKINS_OIDC_ENABLED %}` once the OIDC persona journey has been verified end-to-end is the path back.
