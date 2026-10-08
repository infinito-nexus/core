# Hermes Agent

## Description

[Hermes Agent](https://hermes-agent.nousresearch.com/) is an agent runtime from Nous Research that runs tool-using agent sessions against OpenAI-compatible model backends. In gateway mode it serves an OpenAI-compatible HTTP API, where clients address the agent with the same request shape they use for a plain model. It also ships a web dashboard for chat, sessions, scheduled jobs, skills, configuration and keys.

## Overview

This role deploys Hermes Agent in gateway mode as a Docker service, published behind the reverse proxy on its own subdomain, with its compose service pinned to the isolating runtime that the Kata & gVisor role selects for the host. The OpenAI-compatible API answers on the subdomain. The web dashboard is optional and off by default; switched on, it takes the subdomain root and the API stays under `/v1/` and `/health`. The API server is protected by a generated bearer key, and when the LiteLLM Gateway is part of the deployment the agent's model endpoint is pointed at that gateway with a per-consumer virtual key. Agent state lives in a named volume that the Backup Docker Volumes service captures when it is enabled.

## Features

- **OpenAI-compatible gateway:** The container starts the agent with the `gateway` command and answers OpenAI-style `/v1` requests on its own subdomain.
- **Bearer-key API server:** The API server is gated by a generated `API_SERVER_KEY`, and calls to `/v1/models` without that key are rejected.
- **Optional web dashboard:** With `services.webui.enabled` set, the dashboard runs inside the agent container and is published on the subdomain root. It is off by default. See [Web dashboard](#web-dashboard).
- **Dashboard sign-in:** With Keycloak deployed, the OAuth2 proxy admits the administrator and MCP groups and the dashboard signs them in through OIDC. Without Keycloak the dashboard offers a password form backed by a generated credential of this role.
- **Corporate design:** With the design service deployed, the dashboard and its sign-in page render the corporate palette, logo and title in light and dark mode.
- **Isolating runtime:** The compose service is pinned to Kata Containers when hardware virtualization and the Kata shim are present, and to gVisor otherwise.
- **Gateway-routed models:** With the LiteLLM Gateway deployed, the agent's model base URL points at that gateway and authenticates with a per-consumer virtual key.
- **MCP client contract:** With Home Assistant deployed, the role declares the MCP client side of the platform contract as an internal streamable-HTTP client with a read-only tool policy. Every discovered server is rendered into `config.yaml` under `mcp_servers` in the agent's `HERMES_HOME`, with the bearer referenced as `${env:<ROLE>_MCP_TOKEN}` so the config file carries no secret. The deploy then runs `hermes mcp test` per server and fails when one does not answer.
- **Persistent agent data:** Agent state is stored in a named volume mounted at `/opt/data`, which the Backup Docker Volumes service captures without stopping the container.
- **Health endpoint:** A `/health` endpoint reports the runtime status and backs the container healthcheck.

## Further Resources

- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/PUxq9QvoaTxiHSvdkRsR71)

## Web dashboard

### Switch

The dashboard is controlled by `services.webui.enabled` and is off by default. Set it in the inventory and redeploy:

```yaml
applications:
  web-app-hermes:
    services:
      webui:
        enabled: true
```

| Switch | Subdomain root | Published container ports | Dashboard environment, theme and design carriers |
| --- | --- | --- | --- |
| Off | API server, like every other path | `8642` | None |
| On | Dashboard | `8642` and `9119` | Rendered |

With the switch on, the reverse proxy splits the subdomain by path:

| Path | Target | Protection |
| --- | --- | --- |
| `/` | Dashboard on container port `9119` | Dashboard sign-in, behind the OAuth2 proxy when Keycloak is deployed |
| `/v1/`, `/health` | API server on container port `8642` | `API_SERVER_KEY` |

The Playwright tests that need the dashboard run only while `WEBUI_SERVICE_ENABLED` is true. With the switch off, one test asserts that the root serves no dashboard and that `/v1/models` still answers.

### Sign-in

| Deployment | Sign-in |
| --- | --- |
| Keycloak deployed | `HERMES_DASHBOARD_OIDC_ISSUER` and `HERMES_DASHBOARD_OIDC_CLIENT_ID` point the dashboard at the realm |
| Keycloak absent | `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` carries the administrator username, `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` the generated credential `secrets.credentials.webui_password` of this role |

Read the password from the inventory at `applications.web-app-hermes.secrets.credentials.webui_password`. The platform administrator password is not part of the agent container environment.

### Configuration

`/opt/data/config.yaml` is rendered by the deploy, mounted at `/opt/seed/config.yaml` and copied onto the data volume by `/etc/cont-init.d/00-seed-config` before the gateway starts, so the gateway and the dashboard can write it. The copy runs on every start, so a setting changed in the dashboard lasts until the next deploy. Change the inventory to persist one.

### Corporate design

| Carrier | Content |
| --- | --- |
| `/opt/data/dashboard-themes/corporate.yaml` | Dashboard theme that reads the `--design-*` tokens: `palette`, `typography` and `layout` for surface, text, font and radius, `colorOverrides` for the status colors, `componentStyles` for the sidebar and header surface, `assets.logo` for the logo, `customCSS` for the primary action, navigation states, baked utility colors and plugin colors. `dashboard.theme` pins it as the default. |
| Role stylesheet | Sign-in page only. That page is rendered outside the theme system. |
| Design script | Sets the title and the favicon and mirrors the mode of a chosen built-in theme into `data-design-theme`. |

The corporate theme follows the light or dark mode of the browser. Another theme chosen in the theme switcher renders its own palette.

## MCP Client

Hermes consumes MCP; it does not serve one in this deployment. Every MCP server
role that is deployed alongside and marked shared is discovered through
`MCP_DISCOVERED_SERVERS` and rendered into the agent config at
`/opt/data/config.yaml`.

### Configuration

| Property | Value |
| --- | --- |
| Direction | `client` |
| Transport | Streamable HTTP |
| Config file | `/opt/data/config.yaml`, owned by uid 10000 |
| Auth | `Authorization` header per server, from the discovery data |

The config file is rendered with the container user as owner. Rendering it as
root makes the agent fall back to its built-in defaults **silently**, reporting
only that the server is unknown.

Servers whose auth scheme no client renderer can present are filtered out before
rendering, so the config never carries an unusable credential.

### Verification

The dashboard lists the configured servers on its MCP page. The configured set
is proven at deploy time: the deploy runs `hermes mcp
test <server>` for every configured server and fails when one does not answer. A
successful run reports the negotiated connection and the discovered tool count.
The Playwright spec covers the complementary case, that the agent API holding
the MCP credentials refuses an unauthenticated caller.

### Default state

Off. `mcp.enabled` is false unless an MCP server role is part of the
deployment.

### How to disable

Remove the MCP server roles, or pin `mcp.enabled: false` for this role.
The config then renders with an empty `mcp_servers` map and the verification step
is skipped.
