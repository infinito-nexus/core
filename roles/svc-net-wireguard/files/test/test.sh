#!/usr/bin/env bash
# Deploy-driven e2e: bootstrap empty hosts, register inventories, deploy + test full mesh.
set -euo pipefail

# test containers don't need the internal CA
export CA_CONTAINER_ENABLED=0

: "${WIREGUARD_IMAGE:?}"
: "${WIREGUARD_VERSION:?}"
: "${WIREGUARD_E2E_TIMEOUT:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${DIR}/01_bootstrap.sh"
bash "${DIR}/02_registration.sh"
bash "${DIR}/03_handshake.sh"

echo "ALL CHECKS PASSED"
