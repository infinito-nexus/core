#!/usr/bin/env bash
set -euo pipefail

# Reinstall a selection of apps: cycle the stack (down + up), purge shared
# entities, then run a fresh inventory + deploy on a single distro.
# Same logic as CI version, but WITHOUT destructive cleanup.
#
# Required env:
#   INFINITO_DISTRO     arch|debian|ubuntu|fedora|centos
#   INFINITO_INVENTORY_DIR       /etc/inventories/local-full-server
#   apps       web-app-*
#
# Optional:
#   full_cycle=false   Default. Deploy only (pass 1). Set to 'true' to also run the update pass (pass 2).
#   PYTHON=python3
#   INFINITO_LIMIT_HOST=localhost

PYTHON="${PYTHON:-python3}"

: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (e.g. arch)}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR must be set}"
: "${apps:?apps must be set (e.g. web-app-keycloak)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/load.sh
source "scripts/meta/env/load.sh"

# shellcheck source=scripts/tests/deploy/local/utils/cache-retry.sh
source "${SCRIPT_DIR}/../../../utils/cache-retry.sh"

echo "=== LOCAL: distro=${INFINITO_DISTRO} app=${apps} full_cycle=${full_cycle:-false} ==="
echo "limit_host=${INFINITO_LIMIT_HOST}"
echo "inventory_dir=${INFINITO_INVENTORY_DIR}"
echo

echo ">>> Bringing stack down (replaces former 'make compose-down' prerequisite)"
"${PYTHON}" -m cli.administration.deploy.development down

echo ">>> Ensuring stack is up for distro ${INFINITO_DISTRO}"
"${PYTHON}" -m cli.administration.deploy.development up \
	--when-down

echo ">>> Pre-cleanup shared entities (host docker context)"
apps='matomo' scripts/tests/deploy/local/purge/entity.sh

if [[ "${INFINITO_SKIP_COMPILE:-}" == "true" ]]; then
	echo ">>> Skipping entry.sh bootstrap recompile (INFINITO_SKIP_COMPILE=true)"
else
	echo ">>> Running entry.sh inside container"
	"${PYTHON}" -m cli.administration.deploy.development exec \
		-- bash "${INFINITO_SRC_DIR}/scripts/tests/deploy/local/utils/entry-bootstrap.sh"
fi

deploy_args=(
	--apps "${apps}"
	--inventory-dir "${INFINITO_INVENTORY_DIR}"
	--debug
)

echo ">>> init inventory (ASYNC_ENABLED=false, RUNTIME=dev baked)"
INIT_VARS_BASE='"ASYNC_ENABLED": false, "RUNTIME": "dev"'
if [[ -n "${INIT_VARS_EXTRA:-}" ]]; then
	INIT_VARS="{${INIT_VARS_BASE}, ${INIT_VARS_EXTRA}}"
else
	INIT_VARS="{${INIT_VARS_BASE}}"
fi
"${PYTHON}" -m cli.administration.deploy.development init \
	--apps "${apps}" \
	--inventory-dir "${INFINITO_INVENTORY_DIR}" \
	--vars "${INIT_VARS}"

if [[ "${full_cycle:-false}" == "true" ]]; then
	echo ">>> deploy (PASS 1 sync + PASS 2 async per variant, full_cycle=true)"
	deploy_with_cache_retry "deploy-${apps//[^A-Za-z0-9._-]/-}-full-cycle" -- \
		"${PYTHON}" -m cli.administration.deploy.development deploy \
		"${deploy_args[@]}" --full-cycle
else
	echo ">>> deploy (PASS 1 sync only, full_cycle=false)"
	deploy_with_cache_retry "deploy-${apps//[^A-Za-z0-9._-]/-}" -- \
		"${PYTHON}" -m cli.administration.deploy.development deploy \
		"${deploy_args[@]}"
fi

echo
echo "✅ Done (no deletion)."
