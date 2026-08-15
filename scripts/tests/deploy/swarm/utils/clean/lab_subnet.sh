#!/usr/bin/env bash
# Reclaim whatever occupies THIS worktree's swarm lab subnet.
#
# Required env: INFINITO_SWARM_LAB_SUBNET, INFINITO_SWARM_LAB_NET_NAME.
# Exit codes: 0 the subnet is free, 1 a network survived removal.
set -uo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_repo="$(cd "${_here}/../../../../../.." && pwd)"

# shellcheck source=scripts/meta/env/load.sh
source "${_repo}/scripts/meta/env/load.sh"

: "${INFINITO_SWARM_LAB_SUBNET:?INFINITO_SWARM_LAB_SUBNET must be set}"
: "${INFINITO_SWARM_LAB_NET_NAME:?INFINITO_SWARM_LAB_NET_NAME must be set}"

_occupants=""
for _net in $(docker network ls --format '{{.Name}}' | grep -E "${INFINITO_SWARM_LAB_NET_NAME}" || true); do
	_subnet="$(docker network inspect "${_net}" \
		--format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null)"
	if [ "${_subnet}" = "${INFINITO_SWARM_LAB_SUBNET}" ]; then
		_occupants="${_occupants} ${_net}"
	fi
done

if [ -z "${_occupants// /}" ]; then
	echo ">>> lab-reclaim: ${INFINITO_SWARM_LAB_SUBNET} is free"
	exit 0
fi

DIR_VAR_LIB="$(python3 -c "import yaml,sys;print(yaml.safe_load(open(sys.argv[1]))['DIR_VAR_LIB'])" \
	"${_repo}/group_vars/all/05_paths.yml")"

_rc=0
for _net in ${_occupants}; do
	_nodes="$(docker network inspect "${_net}" \
		--format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null)"
	echo ">>> lab-reclaim: ${_net} holds ${INFINITO_SWARM_LAB_SUBNET}:${_nodes:+ ${_nodes}}"

	if [ -n "${_nodes// /}" ]; then
		# shellcheck disable=SC2086
		timeout 300 bash "${_here}/../unmount/nfs_mounts.sh" ${_nodes} || true
	fi
	bash "${_here}/../unmount/host_state.sh" "${DIR_VAR_LIB}"

	for _node in ${_nodes}; do
		timeout 30 docker exec "${_node}" systemctl stop nfs-ganesha >/dev/null 2>&1
		timeout 30 docker kill "${_node}" >/dev/null 2>&1
		timeout 15 docker network disconnect -f "${_net}" "${_node}" >/dev/null 2>&1
		timeout 30 docker rm -f "${_node}" >/dev/null 2>&1
	done

	timeout 30 docker network rm "${_net}" >/dev/null 2>&1
	timeout 30 docker volume rm "${_net%-"${INFINITO_SWARM_LAB_NET_NAME}"}_nfs-export" >/dev/null 2>&1
	if docker network inspect "${_net}" >/dev/null 2>&1; then
		echo "!!! lab-reclaim: '${_net}' survived removal; clear with 'make swarm-clean'." >&2
		_rc=1
	fi
done

exit "${_rc}"
