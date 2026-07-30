#!/usr/bin/env bash
# shellcheck disable=SC2034  # variables are consumed by callers that source this file

# Naming constants are the SPOT in default.env, shared with the Python harness
# (utils/tests/swarm/*).
_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../../.." && pwd)"
_default_env="${_repo_root}/default.env"

_swarm_topology_sources() {
	if [ -f "${_repo_root}/.env" ]; then
		grep -hE '^INFINITO_SWARM_[A-Z0-9_]+=' "${_repo_root}/.env" || [ "$?" -eq 1 ]
	fi
	grep -hE '^INFINITO_SWARM_[A-Z0-9_]+=' "$_default_env"
}

_swarm_topology_unparsable="$(_swarm_topology_sources | grep -vE '^[A-Z0-9_]+=([^"]*|"[^"]*")$' || [ "$?" -eq 1 ])"
if [ -n "${_swarm_topology_unparsable}" ]; then
	echo "[ERROR] unparsable swarm topology assignment(s): ${_swarm_topology_unparsable}" >&2
	exit 1
fi

# shellcheck source=/dev/null
source <(_swarm_topology_sources | sed -E 's/^([A-Z0-9_]+)="?([^"]*)"?$/: "${\1:=\2}"/')

: "${SWARM_NAME:?SWARM_NAME is required (cluster id) - pass name= to the make target}"
SWARM_PREFIX="${SWARM_NAME}-"

MGR="${SWARM_PREFIX}${INFINITO_SWARM_MGR_NAME}"

NFS_EXPORT_BASE="$(grep -E '^  export_base:' "${_repo_root}/roles/svc-storage-nfs-server/meta/services.yml" | awk '{print $2}')"
: "${NFS_EXPORT_BASE:?export_base missing in svc-storage-nfs-server meta/services.yml}"

NFS_STATE_SUBDIR="$(grep '^STATE_SUBDIR = ' "${_repo_root}/utils/storage/nfs.py" | cut -d'"' -f2)"
: "${NFS_STATE_SUBDIR:?STATE_SUBDIR missing in utils/storage/nfs.py}"

NFS_STATE_PATH="${NFS_EXPORT_BASE}/${NFS_STATE_SUBDIR}"

NFS_SERVER="${SWARM_PREFIX}${INFINITO_SWARM_NFS_NAME}"

BACKUP_NODE="${SWARM_PREFIX}${INFINITO_SWARM_BACKUP_NAME}"

SWARM_LAB_NETWORK="${SWARM_PREFIX}${INFINITO_SWARM_LAB_NET_NAME}"

WRK1="${SWARM_PREFIX}${INFINITO_SWARM_WRK1_NAME}"

WRK2="${SWARM_PREFIX}${INFINITO_SWARM_WRK2_NAME}"

MGR_IP="${INFINITO_SWARM_MGR_IP}"

NFS_IP="${INFINITO_SWARM_NFS_IP}"

BACKUP_IP="${INFINITO_SWARM_BACKUP_IP}"
