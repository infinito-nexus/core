#!/usr/bin/env bash
#
# Resolve whether a pull request touches the agent platform and write
# `affected` to GITHUB_OUTPUT. The `detect-agents-scope` job calls this and
# the agents CI lane runs only when the answer is true, so a pull request that
# touches no agent code never spends a runner on the agents workflow.
#
# Inputs via env:
#   BASE_SHA  the pull-request base commit the diff is taken against.
#
# Outputs (GITHUB_OUTPUT):
#   affected=true|false  true when a changed path is under agents/, the agents
#                        CLI, an AI service role, an agent-platform role or the
#                        agents bundle inventory.

set -euo pipefail

: "${BASE_SHA:?Missing BASE_SHA}"
: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

pattern='^(agents/|cli/agents/|roles/svc-ai-|roles/web-app-workspace/|roles/web-app-agent-fixture/|roles/dsk-agentbox/|inventories/bundles/servers/agents/)'

changed="$(git diff --name-only "${BASE_SHA}" HEAD)"

if grep -qE "${pattern}" <<<"${changed}"; then
	affected=true
else
	affected=false
fi

printf 'affected=%s\n' "${affected}" >>"${GITHUB_OUTPUT}"
echo "Agent-platform change detected: ${affected}"
