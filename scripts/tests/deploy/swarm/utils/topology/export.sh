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
} >>"${GITHUB_ENV}"
