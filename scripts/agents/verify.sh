#!/usr/bin/env bash
set -euo pipefail

# Deploy the agents bundle and run the agent verification scenarios.
# Inputs (env, set by the Makefile from make vars):
#   mode     - compose | swarm; empty runs both in sequence
#   scenario - a single scenario id to run against the already-running stack
#              (no redeploy), for the edit-test loop
# Swarm runs on a worktree slot between 3 and 10 (INFINITO_AGENTS_SWARM_SLOT).

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
. "${_repo_root}/scripts/meta/env/load.sh"

cd "${_repo_root}"

mode="${mode:-}"
scenario="${scenario:-}"

if [ -n "${scenario}" ]; then
	exec "${PYTHON}" -m cli.agents.scenarios --scenario "${scenario}"
fi

assert_swarm_slot() {
	local slot="${INFINITO_AGENTS_SWARM_SLOT:-}" # nocheck: CI-provided worktree slot, bridged by the workflow, not a default.env static value
	[ -n "${slot}" ] || return 0
	case "${slot}" in
	'' | *[!0-9]*)
		echo "agents-verify: INFINITO_AGENTS_SWARM_SLOT must be a number in 3..10, got '${slot}'." >&2
		exit 2
		;;
	esac
	if [ "${slot}" -lt 3 ] || [ "${slot}" -gt 10 ]; then
		echo "agents-verify: swarm runs on a worktree slot between 3 and 10, got ${slot}." >&2
		echo "Fix: set INFINITO_AGENTS_SWARM_SLOT (the worktree slot) to a value in 3..10." >&2
		exit 2
	fi
}

verify_mode() {
	local deploy_mode="$1"
	if [ "${deploy_mode}" = swarm ]; then
		assert_swarm_slot
	fi
	INFINITO_DEPLOY_MODE="${deploy_mode}" make compose-deploy bundles=agents
	"${PYTHON}" -m cli.agents.scenarios --mode "${deploy_mode}"
}

case "${mode}" in
compose | swarm)
	verify_mode "${mode}"
	;;
"")
	verify_mode compose
	verify_mode swarm
	;;
*)
	echo "agents-verify: mode must be compose or swarm, got '${mode}'." >&2
	exit 2
	;;
esac
