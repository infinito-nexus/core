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

for _node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}" "${BACKUP_NODE}"; do
	timeout 60 docker exec "${_node}" systemctl stop docker.socket docker 2>/dev/null
done

timeout 600 bash "$(dirname "$0")/../unmount_nfs_mounts.sh" "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}"

_act_containers="$(timeout 15 docker ps --filter name=^act- --format '{{.Names}}' 2>/dev/null)"
if [ -n "${_act_containers}" ]; then
	# shellcheck disable=SC2086
	timeout 300 bash "$(dirname "$0")/../unmount_nfs_mounts.sh" ${_act_containers}
fi

if timeout 15 mountpoint -q "${DIR_VAR_LIB}" 2>/dev/null; then
	timeout 30 umount -lf "${DIR_VAR_LIB}"
fi

timeout 30 docker exec "${NFS_SERVER}" systemctl stop nfs-ganesha 2>/dev/null

for _node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}" "${BACKUP_NODE}"; do
	timeout 90 docker stop -t 30 "${_node}" 2>/dev/null
	timeout 15 docker network disconnect -f "${SWARM_LAB_NETWORK}" "${_node}" 2>/dev/null
	for _round in 1 2 3 4 5; do
		timeout 30 docker rm -f "${_node}" 2>/dev/null
		timeout 15 docker inspect "${_node}" >/dev/null 2>&1
		_inspect_rc=$?
		[ "${_inspect_rc}" -eq 0 ] || [ "${_inspect_rc}" -eq 124 ] || break
		sleep 3
	done
	if [ "${_inspect_rc}" -eq 0 ] || [ "${_inspect_rc}" -eq 124 ]; then
		echo "WARNING: could not remove '${_node}': its init is gone but containerd never sent an exit event. Clear it with 'systemctl restart containerd' (kills every container) or a reboot; a docker restart does NOT help." >&2
	fi
done
timeout 30 docker network rm "${SWARM_LAB_NETWORK}" 2>/dev/null
exit 0
