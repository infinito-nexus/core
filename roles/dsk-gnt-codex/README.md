# Codex

## Description

[Codex](https://developers.openai.com/codex/) is OpenAI's coding agent. It runs as a terminal CLI and as an extension of the Code editor.

## Overview

This role installs the pinned `@openai/codex` CLI on a workstation and manages the connection shared by the CLI and the Codex editor extension in `~/.codex/config.toml`. The `codex-mode` switch it installs selects either the platform's model gateway or the user's own ChatGPT subscription.

The local gateway may forward requests to external providers according to the chosen model. A local gateway URL does not imply local inference.

The switch rewrites only the keys it owns in `config.toml` (`model`, `model_provider`, `model_reasoning_effort`, `forced_login_method`, the context limits and `[model_providers.infinito]`), so trusted projects, personal settings and every `[mcp_servers.*]` table that Codex or another role such as `dsk-blender` added survive a redeploy; comments in the file do not. The provider speaks the `responses` wire API, the only one the pinned Codex accepts.

## Features

- **Pinned CLI:** the `@openai/codex` package is installed at the version `services.codex.npm_version` pins.
- **One switch for CLI and editor:** `codex-mode gateway` and `codex-mode abo` move the CLI and the editor extension between the gateway and the subscription together.
- **Credential helper:** gateway mode reads the inventory's virtual key through a command-backed helper, so the key is neither embedded in TOML nor taken from a desktop environment variable.
- **Preserved settings:** the switch keeps `auth.json` and unrelated TOML settings, including MCP servers.
- **Deployment validation:** a deploy that manages the connection checks both modes and sends a bounded request to the Responses API.

## Subscription and gateway

Close Code and end existing Codex sessions before switching:

```bash
codex-mode gateway
codex-mode abo
codex-mode status
```

`codex-mode api` is an alias for `gateway`. Reopen Code and start a new Codex
session after switching. In subscription mode, run `codex login` and select
ChatGPT if an account is not already connected. Gateway mode uses the inventory's
virtual key automatically; it does not require an OpenAI API key login.

The gateway provider uses the Responses API and a command-backed credential
helper. The private `~/.config/infinito/codex.json` stores the deployment payload
and selected mode with permissions `0600`. The key is not embedded in TOML or
dependent on a desktop environment variable. The legacy environment.d file is
removed. Existing process environments require restarting affected applications.

The switch preserves `auth.json` and unrelated TOML settings, including MCP
servers. TOML formatting is normalized. Redeployment updates the managed settings
and key while retaining the selected connection mode. `CODEX_HOME` must be unset
or point to `~/.codex`.

## Inventory settings

Set `services.codex.initial_mode` to `gateway` or `abo` for the first deployment.
`subscription_model: ""` uses the native account's model selection.
`reasoning_effort: medium` manages the gateway's reasoning setting and replaces
stale `model_reasoning_effort: none`, which reasoning-only upstream endpoints
reject. Subscription mode removes this gateway override. Responses validation
sends the same reasoning effort as the managed client.
`context_tokens` and `auto_compact_tokens` apply only in gateway mode; use explicit
values matching the loaded model or `0` to leave them unmanaged. Configure
`editor_data_dir` to detect a running editor before writing, or explicitly use
an empty string on a host without an editor.

## Deployment validation

The role installs and runs a persistent validation script. It checks both modes
with the installed native CLI and any installed Codex editor binaries, verifies
the credential helper in an isolated temporary home, and sends a bounded request
to `/v1/responses` using the selected model and consumer key. Saved account logins
and the current mode are not changed by these tests. `services.codex.validation_timeout`
sets each operation's timeout in seconds.

The CLI test repeats this validation. LiteLLM additionally checks the Responses
endpoint for every model assigned to the Codex consumer. A successful Chat
Completions or Anthropic Messages probe alone does not validate Codex compatibility.

## Further Resources

- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
