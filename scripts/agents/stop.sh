#!/usr/bin/env bash
set -euo pipefail

# Suspend the running agent instances without revoking them (the kill
# switch): the deployed orchestrator blocks each agent LiteLLM key, stops
# every broker-managed container and disables every agent LDAP account. A
# teardown (not this target) revokes. The suspend is owned by the orchestrator;
# this reaches it through the documented make compose-app-exec interface.
# Inputs (make vars):
#   orchestrator - orchestrator container name in the running stack
#                  (deploy-resolved); required
#   cmd          - the orchestrator's suspend command; required

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${_repo_root}"

orchestrator="${orchestrator:-}"
cmd="${cmd:-}"
if [ -z "${orchestrator}" ] || [ -z "${cmd}" ]; then
	echo "agents-stop: pass orchestrator=<container> and cmd=<suspend command> (the orchestrator owns the kill switch)." >&2
	echo "Suspend blocks agent keys, stops broker-managed containers and disables agent accounts; a teardown (not this target) revokes." >&2
	exit 2
fi

make compose-app-exec app="${orchestrator}" cmd="${cmd}"
