# Hermes Agent

## Description

[Hermes Agent](https://hermes-agent.nousresearch.com/) is an agent runtime from Nous Research that runs tool-using agent sessions against OpenAI-compatible model backends. In gateway mode it serves an OpenAI-compatible HTTP API, where clients address the agent with the same request shape they use for a plain model. It also ships a web dashboard for chat, sessions, scheduled jobs, skills, configuration and keys.

## Overview

This role deploys Hermes Agent in gateway mode as a Docker service, published behind the reverse proxy on its own subdomain, with its compose service pinned to the isolating runtime that the Kata & gVisor role selects for the host. The OpenAI-compatible API answers on the subdomain. The web dashboard is optional and off by default; switched on, it takes the subdomain root and the API stays under `/v1/` and `/health`. The API server is protected by a generated bearer key, and when the LiteLLM Gateway is part of the deployment the agent's model endpoint is pointed at that gateway with a per-consumer virtual key. Agent state lives in a named volume that the Backup Docker Volumes service captures when it is enabled.

## Cosmos

The diagram places Hermes Agent in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_ai_litellm["svc-ai-litellm 🐳🐝"]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
        dep_svc_net_tor["svc-net-tor 🐳🐝"]
        dep_svc_virt_kata["svc-virt-kata 💻"]
        dep_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_svc_design["web-svc-design 💻"]
    end
    subgraph role [web-app-hermes 🐳🐝]
        svc_hermes["hermes"]
        svc_webui["webui"]
        svc_kata["kata"]
        svc_sso["sso"]
        svc_logout["logout ❌"]
        svc_litellm["litellm"]
        svc_dashboard["dashboard"]
        svc_matomo["matomo"]
        svc_design["design"]
        svc_prometheus["prometheus"]
        svc_tor["tor"]
        svc_container_backup["container_backup"]
    end
    subgraph dependents [Dependents]
        dpt_svc_ai_robot["svc-ai-robot 💻"]
        dpt_svc_db_qdrant["svc-db-qdrant 🐳🐝"]
        dpt_web_app_baserow["web-app-baserow 🐳🐝"]
        dpt_web_app_checkmk["web-app-checkmk 🐳🐝"]
        dpt_web_app_fider["web-app-fider 🐳🐝"]
        dpt_web_app_gitea["web-app-gitea 🐳🐝"]
        dpt_web_app_gitlab["web-app-gitlab 🐳🐝"]
        dpt_web_app_homeassistant["web-app-homeassistant 🐳🐝"]
        dpt_web_app_jellyfin["web-app-jellyfin 🐳🐝"]
        dpt_web_app_jenkins["web-app-jenkins 🐳🐝"]
        dpt_web_app_listmonk["web-app-listmonk 🐳🐝"]
        dpt_web_app_mattermost["web-app-mattermost 🐳🐝"]
        dpt_more["..."]
    end
    dep_svc_ai_litellm -. "0..1" .-> svc_litellm
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
    dep_svc_net_tor -. "0..1" .-> svc_tor
    dep_svc_virt_kata -- "1:1" --> svc_kata
    dep_web_app_dashboard -. "0..1" .-> svc_dashboard
    dep_web_app_keycloak -. "0..1" .-> svc_sso
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_svc_design -. "0..1" .-> svc_design
    svc_hermes -- "1:1" --> dpt_more
    svc_hermes -. "0..1" .-> dpt_svc_ai_robot
    svc_hermes -. "0..1" .-> dpt_svc_db_qdrant
    svc_hermes -. "0..1" .-> dpt_web_app_baserow
    svc_hermes -. "0..1" .-> dpt_web_app_checkmk
    svc_hermes -. "0..1" .-> dpt_web_app_fider
    svc_hermes -. "0..1" .-> dpt_web_app_gitea
    svc_hermes -. "0..1" .-> dpt_web_app_gitlab
    svc_hermes -. "0..1" .-> dpt_web_app_homeassistant
    svc_hermes -. "0..1" .-> dpt_web_app_jellyfin
    svc_hermes -. "0..1" .-> dpt_web_app_jenkins
    svc_hermes -. "0..1" .-> dpt_web_app_listmonk
    svc_hermes -. "0..1" .-> dpt_web_app_mattermost
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

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

## Quick Setup

### Development

Clone, set up the workstation, and deploy Hermes Agent onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-hermes full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Hermes Agent to a managed server (the mounted volume persists the inventory):

```bash
APP=web-app-hermes
HOST=<your-server>
DOMAIN=<your-domain>
TLS_MODE=self_signed
SSH_PUBLIC_KEY="<your-ssh-public-key>"

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  -e APP="$APP" -e HOST="$HOST" -e DOMAIN="$DOMAIN" -e TLS_MODE="$TLS_MODE" -e SSH_PUBLIC_KEY="$SSH_PUBLIC_KEY" \
  ghcr.io/infinito-nexus/core/debian bash -c '
    INVENTORY=/etc/infinito.nexus/inventories/production
    infinito administration inventory provision "$INVENTORY" \
      --inventory-file "$INVENTORY/devices.yml" \
      --host "$HOST" \
      --include "$APP" \
      --vars "{\"TLS_MODE\": \"$TLS_MODE\", \"DOMAIN_PRIMARY\": \"$DOMAIN\", \"users\": {\"administrator\": {\"authorized_keys\": [\"$SSH_PUBLIC_KEY\"]}}}" &&
    infinito administration deploy dedicated "$INVENTORY/devices.yml" \
      --password-file "$INVENTORY/.password" \
      --diff -vv'
```

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

`/opt/data/config.yaml` is rendered by the deploy and mounted as a single file, so the dashboard cannot write it. A theme chosen in the theme switcher lasts until the next page load. Change the inventory and redeploy to persist a setting.

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

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
