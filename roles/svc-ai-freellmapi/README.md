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

The dashboard and API are published on `http://127.0.0.1:7991`. The container
listens on port 3001. Its host binding is always loopback, including on hosts
whose other applications use a broader `DOCKER_BIND_HOST`.

The first dashboard account is created automatically before the HTTP listener
starts, using `lookup('users', 'platform_administrator').email` and `.password`.
The role requires a valid email and a password of at least eight characters.
Log in with these credentials and add the provider keys you want to use.
After the container starts, the role reconciles the single dashboard account
through the installed FreeLLMAPI auth service. Redeploys update its email and
password to the current platform administrator credentials. Matching credentials
cause no account writes; a password change uses the upstream reset operation,
which invalidates existing dashboard sessions. Email changes retain the account
ID. An installation with multiple dashboard accounts fails instead of selecting
an arbitrary account. Provider keys and routing data are preserved.

Every deploy verifies the resulting credentials through `/api/auth/login` and
the authenticated `/api/auth/me`, then removes the temporary session. Rejected
logins fail the deploy even if the container is healthy. Credentials travel on
standard input to an unconditionally masked task; only a fixed success/failure
message is shown. Reconciliation runs in a separate Node process, so it opens the
running database through the image's internal `db/index.js` `connectDb` export
before using the auth service exports; both must be checked when changing the
image version.
Under **Keys**, copy the unified API key for clients. Model
availability depends on your configured providers and their quotas; deploying
this role does not supply provider accounts or bypass their limits.

## Claude Code

### Through the managed LiteLLM gateway

For the managed Claude and Codex setup, keep LiteLLM as the client endpoint.
Every deploy reads the unified key FreeLLMAPI issued through the authenticated
`/api/settings/api-key` endpoint and persists it in the token store for
`platform_administrator`. Select both roles and deploy them: LiteLLM publishes
`freellmapi/auto` with that key and validates the upstream. Clients continue
using LiteLLM virtual keys, not this upstream key. Regenerating the key in the
dashboard takes effect with the next deploy of both roles.
See [the LiteLLM integration](../svc-ai-litellm/README.md#optional-freellmapi-upstream)
for automatic routing, capability declarations and protocol validation.
Do not run FreeLLMAPI's client setup commands over the Infinito-managed client
configuration, or configure FreeLLMAPI to forward back to LiteLLM.

### Standalone access

Use the unified key from the dashboard. The native Anthropic endpoint does not
need a LiteLLM translation layer:

```bash
read -rsp 'FreeLLMAPI unified key: ' FREELLMAPI_TOKEN
ANTHROPIC_BASE_URL=http://127.0.0.1:7991 \
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
configuration as a mapping. It can declare
provider `keys`, `customProviders` such as LM Studio, `models`, `fallback`, and
`routing`. Entries with credentials belong in the encrypted inventory. The
role always passes it as `FREEAPI_CONFIG_JSON`, adding the central platform
administrator under `admin`. An inventory-supplied `startup_config.admin` cannot
override this identity. The rendered environment contains the administrator
password and must retain the framework's credential-file protections.
Upstream still ignores `admin` on already initialized installations; the
post-start reconciliation is what handles credential changes on redeploy.

Provider keys are encrypted in the `freellmapi_data` volume mounted at
`/app/server/data`. Preserve both that volume and the vaulted
`secrets.credentials.encryption_key`; changing the encryption key alone makes
existing stored provider keys unreadable. The optional volume-backup service
stops the container while copying the SQLite state.

The role does not mount the Docker socket or install the upstream optional
Watchtower updater. Image changes are deployed through the inventory.

## Test upstream

`services.mock.enabled` starts a deterministic OpenAI-compatible test upstream
from the FreeLLMAPI image and adds it as an extra `customProviders` entry. It
answers `/v1/models` and `/v1/chat/completions`, both streaming and
non-streaming. It answers a tool request with a call derived from the tool
schema, and every other request with `OK`. It needs no key and receives none of
the gateway's secrets. The flag is off by default. Only the matrix variant
turns it on, so a CI round can route and validate without provider accounts.
Production inventories must leave it off.

See the upstream [installation guide](https://github.com/tashfeenahmed/freellmapi/blob/v0.16.15/docs/en/install/01-install.md)
for first-account setup and declarative configuration.
