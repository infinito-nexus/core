# FreeLLMAPI

## Description

[FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi) is an independently selectable
alternative LLM gateway with a local provider dashboard, automatic routing and
OpenAI-compatible and Anthropic-compatible APIs. The role runs the published
`ghcr.io/tashfeenahmed/freellmapi:v0.16.15` image.

## Overview

The role is registered as `svc-ai-freellmapi`. Its templates and metadata are
tested; a complete reference-distribution deploy is still pending, so its
lifecycle is `pre-alpha`.

## Features

- **Separate gateway:** runs alongside LiteLLM without replacing its configuration.
- **Native client APIs:** exposes OpenAI-compatible and Anthropic-compatible endpoints.
- **Persistent state:** retains encrypted provider credentials and routing settings.
- **Local dashboard:** publishes only on the host's loopback interface.

## Deployment

Select `svc-ai-freellmapi` in the inventory and provision its credentials before
deploying it with `--id svc-ai-freellmapi`. It does not require LiteLLM or Ollama.
The role supports compose mode; swarm mode is disabled because its SQLite state
is local to the workstation.

The dashboard and API are published on `http://127.0.0.1:8106`. The container
listens on port 3001. Its host binding is always loopback, including on hosts
whose other applications use a broader `DOCKER_BIND_HOST`.

Open the dashboard, complete the upstream first-account setup, and add the
provider keys you want to use. Docker forwards local browser requests through a
bridge; if setup asks for its one-time code, read it locally from the FreeLLMAPI
container log. Under **Keys**, copy the unified API key for clients. Model
availability depends on your configured providers and their quotas; deploying
this role does not supply provider accounts or bypass their limits.

## Claude Code

Use the unified key from the dashboard. The native Anthropic endpoint does not
need a LiteLLM translation layer:

```bash
read -rsp 'FreeLLMAPI unified key: ' FREELLMAPI_TOKEN
ANTHROPIC_BASE_URL=http://127.0.0.1:8106 \
ANTHROPIC_AUTH_TOKEN="$FREELLMAPI_TOKEN" \
ANTHROPIC_API_KEY='' \
ANTHROPIC_DEFAULT_HAIKU_MODEL=auto \
ANTHROPIC_DEFAULT_SONNET_MODEL=auto \
ANTHROPIC_DEFAULT_OPUS_MODEL=auto \
CLAUDE_CODE_SUBAGENT_MODEL=auto \
claude --model auto
unset FREELLMAPI_TOKEN
```

For a separate Code profile, set the same environment variables in that
profile's `claudeCode.environmentVariables` and enable
`claudeCode.disableLoginPrompt`. Keep the subscription profile separate.
The existing `claude-gateway` wrapper continues to target LiteLLM.

## Configuration and persistence

`services.freellmapi.startup_config` accepts the upstream declarative startup
configuration as a mapping. It is empty for interactive setup. It can declare
provider `keys`, `customProviders` such as LM Studio, `models`, `fallback`, and
`routing`. Entries with credentials belong in the encrypted inventory. The
role passes a populated mapping as `FREEAPI_CONFIG_JSON`.

Provider keys are encrypted in the `freellmapi_data` volume mounted at
`/app/server/data`. Preserve both that volume and the vaulted
`secrets.credentials.encryption_key`; changing the encryption key alone makes
existing stored provider keys unreadable. The optional volume-backup service
stops the container while copying the SQLite state.

The role does not mount the Docker socket or install the upstream optional
Watchtower updater. Image changes are deployed through the inventory.

See the upstream [installation guide](https://github.com/tashfeenahmed/freellmapi/blob/v0.16.15/docs/en/install/01-install.md)
for first-account setup and declarative configuration.
