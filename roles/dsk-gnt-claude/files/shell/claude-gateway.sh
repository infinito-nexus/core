#!/usr/bin/env bash
# Env file /usr/local/etc/claude-gateway.env (agnt_claude_env_path), KEY=value lines exported into claude:
#   ANTHROPIC_BASE_URL              gateway root; the agent appends /v1/messages itself
#   ANTHROPIC_AUTH_TOKEN            workstation key the gateway accounts the session to
#   ANTHROPIC_MODEL                 optional gateway alias for the main model
#   ANTHROPIC_DEFAULT_HAIKU_MODEL   optional gateway alias for background work
set -euo pipefail

set -a
# shellcheck source=/dev/null
source /usr/local/etc/claude-gateway.env
set +a
exec claude "$@"
