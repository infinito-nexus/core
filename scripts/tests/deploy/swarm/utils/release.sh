#!/usr/bin/env bash
# Param: SWARM_NAME                        cluster id the drill runs under
# Param: keep                              true keeps the cluster and the act outer container up; empty or false releases both
# Param: INFINITO_CONTAINER                worktree label the act outer containers carry
# Param: INFINITO_RESCUE_DIAGNOSTICS_BASE  rescue root, the same path inside the act job and on the host
# Param: $@                                the drill command; its exit code is the script's exit code
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
PLAYWRIGHT_ARTEFACTS=/tmp/playwright-artifacts

: "${SWARM_NAME:?SWARM_NAME is required (the cluster id)}"
: "${keep?keep is required: true keeps the cluster, empty or false releases it}"
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set; source scripts/meta/env/load.sh or invoke via make}"
: "${INFINITO_RESCUE_DIAGNOSTICS_BASE:?INFINITO_RESCUE_DIAGNOSTICS_BASE is not set; source scripts/meta/env/load.sh or invoke via make}"
case "${keep}" in
true | false | "") ;;
*)
	echo "release: keep must be true, false or empty, got '${keep}'" >&2
	exit 2
	;;
esac
[ "$#" -gt 0 ] || {
	echo "usage: release.sh <drill command...>" >&2
	exit 2
}

save_artefacts() {
	local id path out
	local -a ids
	mapfile -t ids < <(docker ps -aq --filter "name=^act-" --filter "label=infinito.worktree=${INFINITO_CONTAINER}")
	for id in "${ids[@]}"; do
		for path in "${INFINITO_RESCUE_DIAGNOSTICS_BASE}" "${PLAYWRIGHT_ARTEFACTS}"; do
			mkdir -p "${path}"
			# nocheck: container-cp - the act outer container runs on this host's own daemon, never on a swarm worker
			if out="$(docker cp "${id}:${path}/." "${path}/" 2>&1)"; then
				echo "==> release: saved ${path} from act container ${id}"
				continue
			fi
			case "${out}" in
			*"Could not find the file"* | *"No such container:path"*)
				echo "==> release: act container ${id} holds no ${path}"
				;;
			*)
				echo "==> release: FAILED to save ${path} from act container ${id}: ${out}" >&2
				return 1
				;;
			esac
		done
	done
}

release() {
	local rc=$? saved=true
	trap - EXIT
	save_artefacts || saved=false
	if [ "${keep}" = true ]; then
		echo "==> release: keep=true, cluster ${SWARM_NAME} stays up; release it with make swarm-down name=${SWARM_NAME}"
		exit "${rc}"
	fi
	SWARM_NAME="${SWARM_NAME}" INFINITO_KEEP_SWARM_NODES=false \
		bash "${SCRIPT_DIR}/clean/teardown.sh"
	if [ "${saved}" = true ]; then
		bash "${REPO_ROOT}/scripts/tests/deploy/act/down_act_outer.sh"
	else
		echo "==> release: the act outer container stays because its artefacts could not be copied; copy them, then run make swarm-down name=${SWARM_NAME}" >&2
		[ "${rc}" -ne 0 ] || rc=1
	fi
	exit "${rc}"
}
trap release EXIT

"$@"
