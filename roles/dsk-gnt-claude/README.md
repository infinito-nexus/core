# Claude Code

## Description

[Claude Code](https://code.claude.com/) is Anthropic's terminal coding agent. This role installs it on a workstation and points it at the platform's own model gateway instead of the vendor API.

## Overview

The agent speaks the Anthropic Messages API, which the LiteLLM gateway serves alongside its OpenAI routes. The role writes `~/.claude/settings.json` with an `env` block carrying the gateway URL, the workstation's key and the model aliases to use, so every request leaves the machine through the gateway and is accounted there.

The gateway mints its virtual keys from the inventory it is deployed from, and a workstation is deployed from a different one. The key is therefore an operator-supplied credential on the workstation side: mint it on the server, then put it into the workstation inventory.

## Features

- **Gateway-backed:** `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` point the agent at the platform gateway.
- **Explicit models:** `ANTHROPIC_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL` name gateway aliases, because the vendor's own model ids do not exist there.
- **No configuration without a key:** the settings file is written only once both the gateway URL and the key are set.
- **User-owned:** the file belongs to the workstation user and is readable only by them.
