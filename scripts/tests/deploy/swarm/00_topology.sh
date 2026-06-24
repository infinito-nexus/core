#!/usr/bin/env bash
# shellcheck disable=SC2034  # variables are consumed by callers that source this file

# Naming constants are the SPOT in default.env, shared with the Python harness
# (utils/tests/swarm/*). Read default.env directly (not the generated .env): the
# workflow sources this file before `make dotenv` runs, so .env may not exist yet.
_default_env="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)/default.env"
# shellcheck source=/dev/null
source <(grep -E '^INFINITO_SWARM_[A-Z0-9_]+=' "$_default_env")

# Mandatory cluster-id prefix so every swarm-test cluster gets distinct container +
# network names and never reuses a shared default. Callers (Makefile targets, the
# workflow) must set SWARM_NAME. SOURCE this file (not literal-dump) so it expands.
: "${SWARM_NAME:?SWARM_NAME is required (cluster id) - pass name= to the make target}"
SWARM_PREFIX="${SWARM_NAME}-"

# Manager-node container name in the simulated swarm.
MGR="${SWARM_PREFIX}${INFINITO_SWARM_MGR_NAME}"

# Base export path on the NFS server that backs swarm-shared volumes.
NFS_EXPORT_BASE="${INFINITO_SWARM_NFS_EXPORT_BASE}"

# NFS-server container name in the simulated swarm.
NFS_SERVER="${SWARM_PREFIX}${INFINITO_SWARM_NFS_NAME}"

# Docker bridge network that links every simulated swarm container.
SWARM_LAB_NETWORK="${SWARM_PREFIX}${INFINITO_SWARM_LAB_NET_NAME}"

# Worker-node-1 container name in the simulated swarm.
WRK1="${SWARM_PREFIX}${INFINITO_SWARM_WRK1_NAME}"

# Worker-node-2 container name in the simulated swarm.
WRK2="${SWARM_PREFIX}${INFINITO_SWARM_WRK2_NAME}"
