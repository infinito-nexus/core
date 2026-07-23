#!/usr/bin/env bash
# Swarm-specific deploy of the MariaDB database role (svc-db-mariadb) via the swarm-* make targets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/environment/utils/common.sh
source "${SCRIPT_DIR}/utils/common.sh"

cd "${REPO_ROOT}"

echo "Deploying the MariaDB database role ${MARIADB_APP} on a throwaway swarm cluster."
make swarm-zombie app="${MARIADB_APP}"

echo "Releasing the swarm cluster."
make swarm-down name="${MARIADB_APP}"
