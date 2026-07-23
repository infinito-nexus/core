#!/usr/bin/env bash
# Exports the swarm topology SPOT (base.sh) into $GITHUB_ENV so every
# later workflow step sees the node names and NFS paths as plain env vars.
set -euo pipefail

# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "$(dirname "$0")/base.sh"

{
	echo "MGR=${MGR}"
	echo "WRK1=${WRK1}"
	echo "WRK2=${WRK2}"
	echo "NFS_SERVER=${NFS_SERVER}"
	echo "BACKUP_NODE=${BACKUP_NODE}"
	echo "NFS_EXPORT_BASE=${NFS_EXPORT_BASE}"
	echo "NFS_STATE_PATH=${NFS_STATE_PATH}"
	echo "SWARM_LAB_NETWORK=${SWARM_LAB_NETWORK}"
	echo "INFINITO_SWARM_TEST_LABEL=${INFINITO_SWARM_TEST_LABEL}"
	echo "INFINITO_SWARM_LAB_SUBNET=${INFINITO_SWARM_LAB_SUBNET}"
	echo "INFINITO_SWARM_MGR_IP=${INFINITO_SWARM_MGR_IP}"
	echo "INFINITO_SWARM_WRK1_IP=${INFINITO_SWARM_WRK1_IP}"
	echo "INFINITO_SWARM_WRK2_IP=${INFINITO_SWARM_WRK2_IP}"
	echo "INFINITO_SWARM_NFS_IP=${INFINITO_SWARM_NFS_IP}"
	echo "INFINITO_SWARM_BACKUP_IP=${INFINITO_SWARM_BACKUP_IP}"
} >>"${GITHUB_ENV}"
