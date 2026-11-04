# OpenClaw

## Description

[OpenClaw](https://openclaw.ai/) is an open-source personal AI agent that runs on hardware you control. It ships a gateway process with a browser Control UI next to its CLI and TUI, keeps persistent memory and a workspace on disk, and performs browser and filesystem tasks inside its own sandbox.

## Overview

This role deploys OpenClaw as a gateway container behind the reverse proxy on its own canonical domain. Its compose service is pinned to the isolating runtime that the Kata & gVisor role selects for the host, its gateway configuration file is rendered from the role, and its state directory is kept in a persistent volume. Access is fronted by an OAuth2 proxy with Keycloak sign-in when Keycloak is part of the deployment.

## Features

- **Agent gateway:** The container runs the OpenClaw gateway bound to the LAN interface on port 18789, with an HTTP health check against `/healthz`.
- **Isolating runtime:** The compose service is pinned to Kata Containers where `/dev/kvm` and the Kata shim are available, and to gVisor otherwise.
- **Single sign-on:** When Keycloak is deployed, an OAuth2 proxy sits in front of the gateway and admits only members of the `administrator` and `mcp` role groups of this application (`sso.oauth2.allowed_groups` in `meta/services.yml`). Every other Keycloak user, biber included, gets a 403 from the proxy.
- **Trusted-proxy authentication:** With single sign-on, the gateway runs in `gateway.auth.mode: "trusted-proxy"`. It reads the signed-in user from the `X-Forwarded-Preferred-Username` header the front proxy sets from the OAuth2 proxy response, requires `X-Forwarded-User` and the secret header only the front proxy sends, and leaves `gateway.auth.trustedProxy.allowUsers` empty: the OAuth2 proxy admits only the role groups in `sso.oauth2.allowed_groups`, so a user added to such a group in Keycloak reaches the gateway at the next sign-in. The Control UI needs no gateway token in this mode; device pairing still applies to every new browser.
- **Gateway token:** Without single sign-on, a generated gateway token guards the Control UI and the API. With single sign-on, the same secret is the gateway password (`OPENCLAW_GATEWAY_PASSWORD`) for the CLI inside the container, which reaches the gateway over loopback. The Control UI accepts its domain in every network the gateway is served on, such as the clearnet domain and its onion sibling, as its allowed origins.
- **Reverse-proxy trust:** `gateway.trustedProxies` carries only the address space the front proxy connects from: the role subnet pool (`NETWORK_ROLE_SUBNET_POOL`) in compose mode, where the proxy reaches the published port through a role network gateway, and Docker's default overlay pool in swarm mode. Loopback and the other private ranges are no longer trusted. Without the proxy's source the gateway answers a Control UI WebSocket that arrives with forwarded headers with `trusted_proxy_untrusted_source` and closes it before the pairing step, which the Control UI reports as a network failure rather than as a pairing prompt.
- **Proxy-owned secret header:** the vhost sends a header named `x-infinito-sso-proxy-<sso_proxy_secret>` with every request, and `gateway.auth.trustedProxy.requiredHeaders` lists it next to `x-forwarded-user`. A client that reaches the gateway port directly, including a process on the host that connects to the published port, cannot name that header, so the gateway answers its forged identity headers with 401. The gateway sends no failure reason to the client. `files/test/test.sh` asserts the refusal on the published port.
- **Corporate design:** With the design service deployed, the Control UI renders the corporate palette, logo and title in light and dark mode. See [Control UI](#control-ui).
- **Model gateway key:** With the LiteLLM Gateway deployed, that gateway provisions a per-consumer virtual key aliased to this application.
- **MCP client contract:** With Home Assistant deployed, the role declares the MCP client side of the platform contract as an internal streamable-HTTP client with a read-only tool policy. The MCP server list itself lives in `openclaw.json`, not in the container environment.
- **Persistent state:** Memory and workspace live in a volume mounted at `/home/node/.openclaw`, with the rendered `openclaw.json` mounted into it, and are included in the container volume backup when that service is deployed.
- **Compose and Swarm:** The role deploys in both modes and renders the gateway configuration file for the local host and the swarm peers.

## Further Resources

- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/PadoNMo5oju7x3yqNjgCW9)

## Control UI

### Sign-in

The Control UI pairs every new browser once:

1. Open the canonical domain. With single sign-on, sign in at Keycloak and select **Connect**. Without single sign-on, paste `applications.web-app-openclaw.secrets.credentials.gateway_token` into **Gateway Token**, then select **Connect**.
2. List the pending request on the host of the container: `container exec openclaw node dist/index.js devices list`.
3. Approve it: `container exec openclaw node dist/index.js devices approve <requestId>`.
4. Select **Connect** again.

To admit another user with single sign-on, add them to the `administrator` or `mcp` role group of `web-app-openclaw` in Keycloak and deploy this role again.

### Corporate design

| Carrier | Content |
| --- | --- |
| Theme slot of the Control UI | The design script stores the corporate theme in the slot for imported themes and selects it on the first visit. Its tokens read the `--design-*` palette for surfaces, text, borders, accent, focus and font. The theme appears under its own name in **Settings → Appearance** next to Claw, Knot and Dash. |
| Mounted logo set | `favicon.svg`, `favicon-32.png`, `favicon.ico` and `apple-touch-icon.png` of the Control UI are replaced by the generated corporate logo. |
| Design script | Sets the page title and mirrors a color mode chosen in the Control UI into `data-design-theme`. |
| Role stylesheet | Applies only while the corporate theme is selected: status colors, shadows and selection outside the theme slot, the brand color of filled primary controls, flat callouts, and the configured title in place of the product name. |

The corporate theme follows the light, dark or system mode of the Control UI. Claw, Knot, Dash or an imported theme chosen in **Appearance** renders its own palette.

`make design-gallery app=web-app-openclaw` waits three minutes for the pairing approval of its browser before it captures the dashboard views. It keeps the paired browser identity in the Playwright stage directory and reuses it on later runs until a full deploy or a role sync with `pw=` recreates that directory.

## MCP Client

OpenClaw consumes MCP. Every deployed shared MCP server role is discovered
through `MCP_DISCOVERED_SERVERS` and written into the agent configuration.

### Configuration

| Property | Value |
| --- | --- |
| Direction | `client` |
| Transport | Streamable HTTP |
| Config file | `openclaw.json` |
| Auth | `Authorization` header per server, from the discovery data |

Servers whose auth scheme cannot be presented as a header are dropped before
rendering, so no entry carries a credential the server would reject.

### Verification

OpenClaw exposes no administrator-visible list of configured MCP servers, so the
configured set is proven by a CLI test instead:
[`files/test/test.sh`](./files/test/test.sh) first lists the gateway's devices
through the in-container CLI, which proves the CLI credential, then probes the agent's `mcp` surface and
fails when the exec itself fails or the output carries a `failed to start server`
line. The Playwright spec covers the complementary case, that the gateway
holding the MCP credentials refuses an unauthenticated caller.

### Default state

Off. `mcp.enabled` is false unless an MCP server role is part of the
deployment.

### How to disable

Remove the MCP server roles, or pin `mcp.enabled: false` for this role.
The rendered config then contains no MCP server entry.
