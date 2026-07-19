#!/usr/bin/env bash
# Full compose+swarm roundtrip of the PostgreSQL database role (svc-db-postgres).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/environment/utils/common.sh
source "${SCRIPT_DIR}/utils/common.sh"

cd "${REPO_ROOT}"

echo "Running the full compose+swarm roundtrip against the PostgreSQL database role ${POSTGRES_APP}."
make roundtrip apps="${POSTGRES_APP}"
