#!/usr/bin/env bash
# shellcheck disable=SC2034  # variables are consumed by callers that source this file

# Naming constants are the SPOT in default.env, shared with the Python harness
# (utils/tests/swarm/*). Read default.env directly (not the generated .env): the
# workflow sources this file before `make dotenv` runs, so .env may not exist yet.
_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../../.." && pwd)"
_default_env="${_repo_root}/default.env"
# shellcheck source=/dev/null
source <(grep -E '^INFINITO_SWARM_[A-Z0-9_]+=' "$_default_env")

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
