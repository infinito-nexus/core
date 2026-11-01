# Claude Code

## Description

[Claude Code](https://code.claude.com/) is Anthropic's terminal coding agent. This role installs it on a workstation and points it at the platform's own model gateway instead of the vendor API.

## Overview

The agent speaks the Anthropic Messages API, which the LiteLLM gateway serves alongside its OpenAI routes. The role writes the launcher `/usr/local/bin/claude-gateway`, which exports the gateway URL, the workstation's key and the model aliases and then starts `claude`. A session started with `claude-gateway` sends every request through the gateway, where it is accounted; a session started with `claude` keeps the user's own login, for example a subscription, and both share `~/.claude` with its memory, skills and projects.

The gateway mints its virtual keys from the inventory it is deployed from, and a workstation is deployed from a different one. The key is therefore an operator-supplied credential on the workstation side: mint it on the server, then put it into the workstation inventory.

## Features

- **Gateway-backed:** `ANTHROPIC_BASE_URL` (the gateway root, since the agent appends `/v1/messages` itself) and `ANTHROPIC_AUTH_TOKEN` point the agent at the platform gateway.
- **Explicit models:** `ANTHROPIC_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL` name gateway aliases, because the vendor's own model ids do not exist there. `services.claude.model` and `services.claude.background_model` set them; without a model the gateway's first chat model is used.
- **No configuration without a key:** the launcher is written only once both the gateway URL and the key are set.
- **User-owned:** the launcher belongs to the workstation user and is readable and executable only by them, because it carries the key.
