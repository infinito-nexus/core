#!/usr/bin/env bash
set -euo pipefail

# SPOT: Deploy exactly ONE app across all distros (serial), via the shared
# per-distro loop in scripts/tests/deploy/distros.sh.
#
# Required env:
#   apps="web-app-keycloak"
#   INFINITO_DISTROS="arch debian ubuntu fedora centos"
#   INFINITO_INVENTORY_DIR="/path/to/inventory"
#
# Optional env:
#   PYTHON="python3"
#
# Script-local defaults preserved from the old Make wrapper:
#   MISSING_ONLY=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
else
	echo "[ERROR] Missing env file: scripts/meta/env/load.sh" >&2
	exit 2
fi

: "${apps:?apps is required (e.g. apps=web-app-keycloak)}"
: "${INFINITO_DISTROS:?INFINITO_DISTROS is required (e.g. 'arch debian ubuntu fedora centos')}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR is required}"

: "${PYTHON:=python3}"
: "${MISSING_ONLY:=true}"

export INFINITO_INVENTORY_DIR MISSING_ONLY

echo ">>> Installing CI dependencies"
PYTHON="${PYTHON}" bash "${REPO_ROOT}/scripts/install/python.sh"

exec "${REPO_ROOT}/scripts/tests/deploy/distros.sh" "${SCRIPT_DIR}/one.sh"
