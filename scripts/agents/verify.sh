#!/usr/bin/env bash
set -euo pipefail

# Run the agent verification scenarios.
# Inputs (env, set by the Makefile from make vars):
#   mode     - compose | swarm; empty runs both in sequence
#   scenario - a single scenario id to replay against the already-running stack
#              (no redeploy), for the edit-test loop
# Without scenario, act runs call-test-agents-local.yml, the workflow file the
# CI runs on pull requests, which deploys the agents bundle and plays every
# scenario. Swarm runs on a worktree slot between 3 and 10 (INFINITO_INSTANCE).

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
. "${_repo_root}/scripts/meta/env/load.sh"

cd "${_repo_root}"

mode="${mode:-}"
scenario="${scenario:-}"

case "${mode}" in
'' | compose | swarm) ;;
*)
	echo "agents-verify: mode must be compose or swarm, got '${mode}'." >&2
	exit 2
	;;
esac

if [ -n "${scenario}" ]; then
	exec "${PYTHON}" -m cli.agents.scenarios --scenario "${scenario}" ${mode:+--mode "${mode}"}
fi

if [ "${mode}" != compose ]; then
	slot="${INFINITO_INSTANCE}"
	case "${slot}" in
	'' | *[!0-9]*)
		echo "agents-verify: the worktree slot INFINITO_INSTANCE must be a number in 3..10, got '${slot}'." >&2
		exit 2
		;;
	esac
	if [ "${slot}" -lt 3 ] || [ "${slot}" -gt 10 ]; then
		echo "agents-verify: swarm runs on a worktree slot between 3 and 10, this checkout is on slot ${slot}." >&2
		echo "Fix: run it from a worktree on a slot in 3..10 (make worktree-up), or pass mode=compose." >&2
		exit 2
	fi
fi

ACT_WORKFLOW=".github/workflows/call-test-agents-local.yml" \
	ACT_MATRIX="${mode:+mode:${mode}}" \
	exec bash scripts/tests/deploy/act/workflow.sh
