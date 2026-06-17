#!/usr/bin/env bash
# E2E orchestrator: env-gate, then delegate to local.sh (servers),
# external.sh (server handshakes), mesh.sh (full mesh: all servers + clients).
# Backend pluggable via WIREGUARD_E2E_BACKEND; v1 = "compose" (DinD). Adding
# swarm/kubernetes means swapping local.sh only; external.sh stays unchanged.
set -euo pipefail

# Ephemeral test containers don't need the internal CA; keep `container run` a
# plain passthrough so --device/--sysctl are not misparsed by the CA wrapper.
export CA_CONTAINER_ENABLED=0

: "${WIREGUARD_E2E_BACKEND:=compose}"
: "${WIREGUARD_E2E_SERVER_COUNT:?set WIREGUARD_E2E_SERVER_COUNT (>=3)}"
: "${WIREGUARD_IMAGE:?set WIREGUARD_IMAGE}"
: "${WIREGUARD_VERSION:?set WIREGUARD_VERSION}"
: "${WIREGUARD_E2E_BASE_PORT:?set WIREGUARD_E2E_BASE_PORT}"
: "${WIREGUARD_E2E_WORKDIR:?set WIREGUARD_E2E_WORKDIR}"
: "${WIREGUARD_E2E_TIMEOUT:?set WIREGUARD_E2E_TIMEOUT}"

if [ "${WIREGUARD_E2E_SERVER_COUNT}" -lt 3 ]; then
    echo "FAIL: WIREGUARD_E2E_SERVER_COUNT must be >= 3 (got ${WIREGUARD_E2E_SERVER_COUNT})"
    exit 1
fi
echo "OK: env verified (backend=${WIREGUARD_E2E_BACKEND}, servers=${WIREGUARD_E2E_SERVER_COUNT}, image=${WIREGUARD_IMAGE}:${WIREGUARD_VERSION})"

if [ "${WIREGUARD_E2E_BACKEND}" != "compose" ]; then
    echo "FAIL: backend '${WIREGUARD_E2E_BACKEND}' not implemented yet (only 'compose' in v1)"
    exit 1
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${DIR}/local.sh"
bash "${DIR}/external.sh"
bash "${DIR}/mesh.sh"

echo "ALL CHECKS PASSED"
