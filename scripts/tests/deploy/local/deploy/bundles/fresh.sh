#!/usr/bin/env bash
set -euo pipefail

# One-off deploy of all apps cumulated from one or more inventory bundles.
#
# Usage:
#   INFINITO_BUNDLES="education-suite,startup-essentials" make compose-deploy
#
# Behavior:
#   - Aggregates and deduplicates all role groups declared in each bundle's
#     inventory.yml (see utils.inventory.bundle_apps).
#   - Exports INFINITO_APPS=<csv> and delegates to apps/reinstall/selection.sh.
#   - Defaults INFINITO_FULL_CYCLE=false (override via default.env or by
#     exporting INFINITO_FULL_CYCLE=true).
#
# Required env:
#   INFINITO_BUNDLES            comma-separated bundle names
# Optional env (forwarded to apps/reinstall/selection.sh):
#   INFINITO_FULL_CYCLE         false (default) | true
#   INFINITO_DISTRO             arch|debian|ubuntu|fedora|centos
#   INFINITO_INVENTORY_DIR      /etc/inventories/local-full-server (typical)
#   INFINITO_DEPLOY_TYPE   server|workstation|universal

: "${INFINITO_BUNDLES:?INFINITO_BUNDLES must be set (e.g. INFINITO_BUNDLES=education-suite,startup-essentials)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../.." && pwd)"
cd "${REPO_ROOT}"

PYTHON="${PYTHON:-python3}"
export INFINITO_FULL_CYCLE

echo "=== resolving bundles: ${INFINITO_BUNDLES} ==="

INFINITO_APPS="$("${PYTHON}" -m utils.inventory.bundle_apps "${INFINITO_BUNDLES}")"
export INFINITO_APPS

echo "apps        = ${INFINITO_APPS}"
echo "full_cycle  = ${INFINITO_FULL_CYCLE}"
echo

# Delegate to the selection deploy; that script already cycles the stack (down + up).
exec bash "${SCRIPT_DIR}/../apps/reinstall/selection.sh"
