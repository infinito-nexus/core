#!/usr/bin/env bash
set -euo pipefail

# One-off deploy of all apps cumulated from one or more inventory bundles.
#
# Usage:
#   make compose-deploy bundles="education-suite,startup-essentials"
#
# Behavior:
#   - Aggregates and deduplicates all role groups declared in each bundle's
#     inventory.yml (see utils.inventory.bundle_apps).
#   - Exports apps=<csv> and delegates to apps/reinstall/selection.sh.
#   - Defaults full_cycle=false (override via `full_cycle=true`).
#
# Required env (set by the compose-deploy recipe from `bundles=`):
#   bundles            comma-separated bundle names
# Optional env (forwarded to apps/reinstall/selection.sh):
#   full_cycle         false (default) | true (set by `full_cycle=`)
#   INFINITO_DISTRO             arch|debian|ubuntu|fedora|centos
#   INFINITO_INVENTORY_DIR      /etc/inventories/local-full-server (typical)
#   INFINITO_DEPLOY_TYPE   server|workstation|universal

: "${bundles:?bundles must be set (e.g. bundles=education-suite,startup-essentials)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../.." && pwd)"
cd "${REPO_ROOT}"

PYTHON="${PYTHON:-python3}"
export full_cycle

echo "=== resolving bundles: ${bundles} ==="

apps="$("${PYTHON}" -m utils.inventory.bundle_apps "${bundles}")"
export apps

echo "apps        = ${apps}"
echo "full_cycle  = ${full_cycle:-false}"
echo

# Delegate to the selection deploy; that script already cycles the stack (down + up).
exec bash "${SCRIPT_DIR}/../apps/reinstall/selection.sh"
