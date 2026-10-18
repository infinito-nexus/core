# Codex

## Description

[Codex](https://github.com/openai/codex) is OpenAI's terminal coding agent, installed on a workstation and pointed at this deployment's own model gateway instead of the vendor API.

## Overview

The role installs the `@openai/codex` npm package and, when the workstation also runs [`svc-ai-litellm`](../svc-ai-litellm/), writes a provider profile that sends every completion to the gateway over the loopback address the engine publishes it on. Nothing leaves the machine: the gateway answers on `127.0.0.1`, so the workstation's virtual key never crosses a network.

Codex reads its key from an environment variable rather than from its config file, so the role writes the key to a `0600` file under `~/.config/environment.d/` and names that variable in `config.toml`. A workstation whose gateway lives in another inventory leaves `services.codex.gateway_url` and `credentials.gateway_key` set by hand instead, and the loopback wiring stays out of the way.

## Features

- **Feature:** Describe a capability.
