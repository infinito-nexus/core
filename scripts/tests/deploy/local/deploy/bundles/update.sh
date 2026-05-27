#!/usr/bin/env bash
set -euo pipefail

# Update all apps cumulated from one or more inventory bundles (reuses inventory, no down/up, no purge).
#
# Usage:
#   INFINITO_BUNDLES="education-suite,startup-essentials" make compose-deploy mode=update
#
# Behavior:
#   - Aggregates and deduplicates all role groups declared in each bundle's
#     inventory.yml (see utils.inventory.bundle_apps).
#   - Exports INFINITO_APPS=<csv> and delegates to apps/update/selection.sh.
#   - Does NOT bring the stack down/up and does NOT purge entities.
#   - Requires an already-initialized inventory (see `make compose-deploy` with
#     INFINITO_BUNDLES set, or INFINITO_APPS, for the first run).
#
# Required env:
#   INFINITO_BUNDLES            comma-separated bundle names
# Optional env (forwarded to apps/update/selection.sh):
#   INFINITO_DEBUG              true (default) | false
#   INFINITO_DISTRO             arch|debian|ubuntu|fedora|centos
#   INFINITO_INVENTORY_DIR      /etc/inventories/local-full-server (typical)
#   INFINITO_DEPLOY_TYPE   server|workstation|universal
#   INFINITO_VARIANT            matrix round index to pin redeploy to

: "${INFINITO_BUNDLES:?INFINITO_BUNDLES must be set (e.g. INFINITO_BUNDLES=education-suite,startup-essentials)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../.." && pwd)"
cd "${REPO_ROOT}"

PYTHON="${PYTHON:-python3}"
# Bundle redeploys default to verbose tracing; SPOT default (empty) is
# overridden here only when the caller did not set anything explicit.
INFINITO_DEBUG="${INFINITO_DEBUG:-}"
if [[ -z "${INFINITO_DEBUG}" ]]; then
	INFINITO_DEBUG="true"
fi
export INFINITO_DEBUG

echo "=== resolving bundles: ${INFINITO_BUNDLES} ==="

INFINITO_APPS="$("${PYTHON}" -m utils.inventory.bundle_apps "${INFINITO_BUNDLES}")"
export INFINITO_APPS

echo "apps  = ${INFINITO_APPS}"
echo "debug = ${INFINITO_DEBUG}"
echo

exec bash "${SCRIPT_DIR}/../apps/update/selection.sh"
