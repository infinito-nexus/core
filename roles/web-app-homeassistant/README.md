# Home Assistant

## Description

[Home Assistant](https://www.home-assistant.io/) is an open-source home automation platform that connects smart-home devices from many vendors behind a single local interface. It keeps device state, dashboards, and automation rules on the machine that runs it, and exposes them through a web interface, a REST API, and a built-in MCP server.

## Overview

This role deploys Home Assistant as a container on its own canonical domain behind the reverse proxy, with the configuration directory kept in a persistent volume. It renders a `configuration.yaml` that trusts the proxy through `use_x_forwarded_for` and the project-wide trusted-proxy CIDRs, and it attaches the hub to a shared overlay network. With Hermes Agent deployed alongside it, the role declares the hub as the MCP server of the deployment: an internal `/api/mcp` endpoint plus the long-lived access token that MCP clients present.

## Features

- **Containerized hub:** Runs the official Home Assistant image on both the Docker Compose and Swarm stacks behind the reverse proxy.
- **Reverse-proxy trust:** Renders a `configuration.yaml` with `default_config`, `use_x_forwarded_for`, and the project-wide trusted-proxy CIDRs listed in `trusted_proxies`. In swarm the hub joins the proxy's own overlay, so the forwarded request arrives from that network rather than from the hub's, and trusting only the hub's subnet makes Home Assistant answer every proxied request with HTTP 400.
- **Persistent configuration:** Mounts `/config` as a named volume and hands it to the container backup service when volume backups are part of the deployment.
- **MCP server contract:** Declares the built-in MCP server at `/api/mcp` over streamable HTTP as an internal, bearer-token-authenticated endpoint, and generates the token that MCP clients present. Adding the MCP Server integration itself stays a Home Assistant onboarding step.
- **Token verified against the hub:** Every deploy asks the hub whether the stored token still authenticates and re-mints it when the hub rejects it, then fails the deploy if the fresh token is rejected too. A hub whose `.storage/auth` was recreated leaves a stored token pointing at a deleted refresh token, and clients would receive a 401 on every call.
- **Two-layer tool policy:** Home Assistant offers no per-tool filter of its own; enabling the Assist API always publishes its actuating intents (`HassTurnOn`, `HassTurnOff`, the todo-list writers). The role names those in `tools.mutating`, and `mutating_tools_enabled: false` withholds them from every client's include list, so an agent is offered the read tools only. Entity exposure bounds the rest: the role exposes no entity to Assist, and making the hub actuate anything is an explicit operator step per entity.
- **Guest MCP probe:** A Playwright spec asserts that an unauthenticated request to the MCP endpoint is never answered with a 2xx.
- **Monitoring and dashboard entries:** Registers the hub with the metrics and dashboard services when those are part of the deployment.

## MCP Server

Home Assistant ships the MCP server as a native integration. The role enables it
through `mcp.enabled`, which stays true only while an MCP client role is
part of the deployment.

### Endpoint

| Property | Value |
| --- | --- |
| Transport | Streamable HTTP |
| URL | `http://homeassistant:8123/api/mcp` |
| Exposure | `internal`, container network only |

### Auth

Clients present a long-lived access token as `Authorization: Bearer <token>`. The
token is minted once per deployment and kept in `sys-token-store` under the
`administrator` user, not in the role's `credentials:` block. An unauthenticated
request is answered with 404: Home Assistant does not reveal the endpoint.

### Authorization subject

`auth_subject: administrator`: Home Assistant scopes the token to the account that minted
it. This deployment mints it for the administrator, so a call arrives as the
administrator whoever asked the client. Entity exposure still bounds the reach.
Getting to the tool server is gated on the role's `mcp` RBAC group.

### Tool categories

`tools/list` returns 10 tools: entity control (`HassTurnOn`, `HassTurnOff`),
timers, broadcast, to-do list read and write, date and time, and `GetLiveContext`
for the current state.

### Default state

Off. `mcp.enabled` is false unless `web-app-flowise`, `web-app-hermes`,
`web-app-openclaw` or `web-app-openwebui` is deployed alongside.

### Tool scope

Two controls stack. The actuating tools are named in `tools.mutating`, and
`mutating_tools_enabled: false` withholds them from every client's include
list, so an agent is offered `GetDateTime`, `GetLiveContext` and
`todo_get_items` only. Entity exposure bounds those: only entities exposed to
Assist are reachable, and the role exposes none. Setting
`mutating_tools_enabled: true` offers the actuating tools as well; entity
exposure then decides what they can reach.

### How to disable

Remove the MCP client roles from the deployment, or pin
`mcp.enabled: false` for this role in the inventory. The integration is
then not configured and the endpoint stops answering.
