#!/usr/bin/env bash
# Deploy-driven e2e: bootstrap fresh hosts, deploy the role (server/client/nat),
# then verify the tunnels.
set -euo pipefail

# test containers don't need the internal CA
export CA_CONTAINER_ENABLED=0

: "${WIREGUARD_E2E_TIMEOUT:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${DIR}/01_bootstrap.sh"
bash "${DIR}/02_registration.sh"
bash "${DIR}/03_handshake.sh"

echo "ALL CHECKS PASSED"
