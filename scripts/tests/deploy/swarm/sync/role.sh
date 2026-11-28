#!/usr/bin/env bash
# Param: app                 application id the kept cluster was deployed with
# Param: SWARM_NAME          cluster id the swarm-zombie run used
# Param: variant             variant index of the round the cluster runs
# Param: INFINITO_CONTAINER  worktree label the act job container carries
set -euo pipefail

: "${app:?app=<application_id> required}"
: "${SWARM_NAME:?SWARM_NAME is required (the cluster id)}"
: "${variant:?variant is required (the variant index of the round)}"
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set; source scripts/meta/env/load.sh or invoke via make}"
[[ "${app}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
	echo "swarm-role-sync: app must be an application id, got '${app}'" >&2
	exit 2
}
[[ "${variant}" =~ ^[0-9]+$ ]] || {
	echo "swarm-role-sync: variant must be a variant index, got '${variant}'" >&2
	exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "${SCRIPT_DIR}/../utils/topology/base.sh"

if ! docker inspect --format '{{.State.Running}}' "${MGR}" 2>/dev/null | grep -q '^true$'; then
	echo "swarm-role-sync: the swarm manager '${MGR}' is not running; keep a cluster with make swarm-zombie app=${app} keep=true first" >&2
	exit 1
fi

act_list="$(docker ps -q --filter "name=^act-" --filter "label=infinito.worktree=${INFINITO_CONTAINER}")"
act_ids=()
if [ -n "${act_list}" ]; then
	mapfile -t act_ids <<<"${act_list}"
fi
if [ "${#act_ids[@]}" -eq 0 ]; then
	echo "swarm-role-sync: no running act job container carries infinito.worktree=${INFINITO_CONTAINER}; act removes it after a green job, so only a failed make swarm-zombie app=${app} keep=true leaves one to sync in" >&2
	exit 1
fi
if [ "${#act_ids[@]}" -gt 1 ]; then
	echo "swarm-role-sync: ${#act_ids[@]} running act job containers carry infinito.worktree=${INFINITO_CONTAINER} (${act_ids[*]}); release the stale cluster with make swarm-down name=<cluster-id>" >&2
	exit 1
fi

# shellcheck disable=SC2016  # expanded by the shell inside the act job container
docker exec -i -w "${REPO_ROOT}" -e APP="${app}" -e VARIANT="${variant}" "${act_ids[0]}" \
	bash --noprofile --norc -c 'source scripts/meta/env/load.sh && exec "${PYTHON}" -m utils.tests.swarm.sync --app "${APP}" --variant "${VARIANT}"'
