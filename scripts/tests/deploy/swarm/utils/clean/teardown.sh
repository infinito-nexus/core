#!/usr/bin/env bash
set +e

if [ "${INFINITO_KEEP_SWARM_NODES}" = "true" ]; then
	echo "INFINITO_KEEP_SWARM_NODES=true -> preserving swarm cluster for post-mortem inspection."
	echo "Inspect: make swarm-exec node=swarm-mgr-01 cmd='docker service ls'"
	echo "Release: make swarm-down"
	exit 0
fi

# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "$(dirname "$0")/../topology/base.sh"

REPO_ROOT="$(cd "$(dirname "$0")/../../../../../.." && pwd)"
DIR_VAR_LIB="$(python3 -c "import yaml,sys;print(yaml.safe_load(open(sys.argv[1]))['DIR_VAR_LIB'])" \
	"${REPO_ROOT}/group_vars/all/05_paths.yml")"

timeout 120 bash "$(dirname "$0")/../unmount_nfs_mounts.sh" "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}" || true

if timeout 15 mountpoint -q "${DIR_VAR_LIB}" 2>/dev/null; then
	timeout 30 umount -lf "${DIR_VAR_LIB}" || true
fi

timeout 30 docker exec "${NFS_SERVER}" systemctl stop nfs-ganesha 2>/dev/null || true

for _node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}" "${BACKUP_NODE}"; do
	timeout 30 docker kill "${_node}" 2>/dev/null
	timeout 15 docker network disconnect -f "${SWARM_LAB_NETWORK}" "${_node}" 2>/dev/null
	timeout 30 docker rm -f "${_node}" 2>/dev/null
	timeout 15 docker inspect "${_node}" >/dev/null 2>&1
	_inspect_rc=$?
	if [ "${_inspect_rc}" -eq 0 ] || [ "${_inspect_rc}" -eq 124 ]; then
		echo "WARNING: could not remove '${_node}' (inspect rc=${_inspect_rc}; kernel D-state? stuck NFS mount); a host reboot may be required." >&2
	fi
done
timeout 30 docker network rm "${SWARM_LAB_NETWORK}" 2>/dev/null
exit 0
