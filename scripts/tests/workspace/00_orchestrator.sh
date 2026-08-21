#!/usr/bin/env bash
# Orchestrates the local Infinito.Nexus workspace test suite.
# Serves as a reference for how to deploy and debug applications locally.
# Chdirs to the repository root because pkgmgr images may invoke it elsewhere.
#
# Env:
#   INFINITO_WORKSPACE_TRACKS  space-separated track directories to run, in the
#                              order given (e.g. "base swarm"). Empty runs
#                              base, compose and swarm.
set -euo pipefail

# Force local runtime context.
unset GITHUB_ACTIONS
unset ACT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/workspace/utils/common.sh
source "${SCRIPT_DIR}/utils/common.sh"

cd "${REPO_ROOT}"

ran=0
for track in ${INFINITO_WORKSPACE_TRACKS:?set it or refresh a stale .env with \`make dotenv\`}; do
	track_dir="${SCRIPT_DIR}/${track}"
	if [ ! -d "${track_dir}" ]; then
		echo "FAILURE: no such workspace track: '${track}'" >&2
		exit 1
	fi
	for step in "${track_dir}"/[0-9][0-9]_*.sh; do
		load_repo_env
		ensure_git_safe_directory
		echo "============================================================"
		echo ">>> ${track}/$(basename "${step}")"
		echo "============================================================"
		bash "${step}"
		ran=$((ran + 1))
	done
done

if [ "${ran}" -eq 0 ]; then
	echo "FAILURE: INFINITO_WORKSPACE_TRACKS='${INFINITO_WORKSPACE_TRACKS:-}' ran no step." >&2
	exit 1
fi
