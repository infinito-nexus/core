#!/usr/bin/env bash
# Swarm-specific deploy of the MariaDB database role (svc-db-mariadb) via the swarm-* make targets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/workspace/utils/common.sh
source "${SCRIPT_DIR}/../utils/common.sh"

cd "${REPO_ROOT}"

node_image="$(bash scripts/meta/resolve/image/local.sh):${INFINITO_IMAGE_TAG:?}"
docker image inspect "${node_image}" >/dev/null 2>&1 || {
	echo "FAILURE: ${node_image} is missing. 03_build.sh builds it for ${INFINITO_DISTRO:?}; the swarm nodes must run that image, not a published one." >&2
	exit 1
}

echo "Deploying the MariaDB database role ${MARIADB_APP} on a throwaway swarm cluster."
make swarm-zombie app="${MARIADB_APP}" disable="$(variable_services mariadb node nfs-server)"

echo "Releasing the swarm cluster."
make swarm-down name="${MARIADB_APP}"
