#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/tests/deploy/swarm/00_topology.sh
. "${SCRIPT_DIR}/00_topology.sh"
# shellcheck source=/dev/null
source <(grep -E '^INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR=' "${SCRIPT_DIR}/../../../../.env")

: "${APP_ID:?APP_ID required}"

dest="/tmp/playwright-artifacts/${APP_ID}"
mkdir -p "${dest}"

docker cp "${MGR}:${INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR}/." "${dest}" 2>/dev/null || true
