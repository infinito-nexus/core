#!/usr/bin/env bash
# shellcheck disable=SC2034  # variables are consumed by callers that source this file

# Naming constants are the SPOT in default.env, shared with the Python harness
# (utils/tests/swarm/*). Read default.env directly (not the generated .env): the
# workflow sources this file before `make dotenv` runs, so .env may not exist yet.
_default_env="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)/default.env"
# shellcheck source=/dev/null
source <(grep -E '^INFINITO_SWARM_[A-Z0-9_]+=' "$_default_env")

: "${SWARM_NAME:?SWARM_NAME is required (cluster id) - pass name= to the make target}"
SWARM_PREFIX="${SWARM_NAME}-"

MGR="${SWARM_PREFIX}${INFINITO_SWARM_MGR_NAME}"

NFS_EXPORT_BASE="${INFINITO_SWARM_NFS_EXPORT_BASE}"

NFS_STATE_PATH="${NFS_EXPORT_BASE}/infinito-state"

NFS_SERVER="${SWARM_PREFIX}${INFINITO_SWARM_NFS_NAME}"

SWARM_LAB_NETWORK="${SWARM_PREFIX}${INFINITO_SWARM_LAB_NET_NAME}"

WRK1="${SWARM_PREFIX}${INFINITO_SWARM_WRK1_NAME}"

WRK2="${SWARM_PREFIX}${INFINITO_SWARM_WRK2_NAME}"
