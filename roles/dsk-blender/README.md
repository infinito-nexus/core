# Blender

## Description

[Blender](https://www.blender.org) is a free and open source 3D creation suite covering modelling, sculpting, animation, simulation, rendering and compositing.

## Overview

This role installs Blender on a workstation and connects it to the coding agents the same host deploys, so a model can drive the scene instead of only describing it.

The bridge has two halves. Inside Blender an add-on opens a local socket; outside it the `mcp-for-blender` server speaks the Model Context Protocol over stdio and relays to that socket. Both halves come from the same pinned upstream distribution, which also carries the `install-addon` subcommand this role uses to place the Blender side.

Registration follows the host: the role declares `claude` and `code` as services gated on whether `dsk-gnt-claude` and `dsk-code` are deployed, and registers the server only with the clients that are present. A workstation without either installs Blender and the bridge, and nothing tries to configure an absent editor.

The agents keep their own model wiring. `dsk-gnt-claude` already points at the LiteLLM gateway, so a prompt reaches the local gateway and the resulting tool calls reach Blender.

## Features

- **Agent-driven modelling:** An MCP client creates, edits and renders scenes through Blender's own Python API.
- **Follows the host:** The MCP server is registered with each agent the workstation actually deploys.
- **Pinned bridge:** Add-on and server ship from one version-pinned distribution, so the two halves cannot drift apart.
- **No remote installer:** The server arrives through pipx and the add-on through its own subcommand.

## Further Resources

- [MCP for Blender](https://github.com/ahujasid/mcp-for-blender)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [Blender Python API](https://docs.blender.org/api/current/)
