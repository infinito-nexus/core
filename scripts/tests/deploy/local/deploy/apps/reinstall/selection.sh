#!/usr/bin/env bash
set -euo pipefail

# Reinstall a selection of apps: cycle the stack (down + up), purge shared
# entities, then run a fresh inventory + deploy on a single distro.
# Same logic as CI version, but WITHOUT destructive cleanup.
#
# Required env:
#   INFINITO_DISTRO     arch|debian|ubuntu|fedora|centos
#   INFINITO_INVENTORY_DIR       /etc/inventories/local-full-server
#   INFINITO_DEPLOY_TYPE    server|workstation|universal
#   INFINITO_APPS       web-app-*
#
# Optional:
#   INFINITO_FULL_CYCLE=false   Default. Deploy only (pass 1). Set to 'true' to also run the update pass (pass 2).
#   PYTHON=python3
#   INFINITO_LIMIT_HOST=localhost

PYTHON="${PYTHON:-python3}"

: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (e.g. arch)}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR must be set}"
: "${INFINITO_DEPLOY_TYPE:?INFINITO_DEPLOY_TYPE must be set (server|workstation|universal)}"
: "${INFINITO_APPS:?INFINITO_APPS must be set (e.g. web-app-keycloak)}"

case "${INFINITO_DEPLOY_TYPE}" in
server | workstation | universal) ;;
*)
	echo "[ERROR] Invalid INFINITO_DEPLOY_TYPE: ${INFINITO_DEPLOY_TYPE}" >&2
	exit 2
	;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/load.sh
source "scripts/meta/env/load.sh"

# shellcheck source=scripts/tests/deploy/local/utils/cache-retry.sh
source "${SCRIPT_DIR}/../../../utils/cache-retry.sh"

echo "=== LOCAL: distro=${INFINITO_DISTRO} type=${INFINITO_DEPLOY_TYPE} app=${INFINITO_APPS} full_cycle=${INFINITO_FULL_CYCLE} ==="
echo "limit_host=${INFINITO_LIMIT_HOST}"
echo "inventory_dir=${INFINITO_INVENTORY_DIR}"
echo

echo ">>> Bringing stack down (replaces former 'make compose-down' prerequisite)"
"${PYTHON}" -m cli.administration.deploy.development down

echo ">>> Ensuring stack is up for distro ${INFINITO_DISTRO}"
"${PYTHON}" -m cli.administration.deploy.development up \
	--when-down

echo ">>> Pre-cleanup shared entities (host docker context)"
INFINITO_APPS='matomo' scripts/tests/deploy/local/purge/entity.sh

echo ">>> Running entry.sh inside container"
"${PYTHON}" -m cli.administration.deploy.development exec \
	-- bash "${INFINITO_SRC_DIR}/scripts/tests/deploy/local/utils/entry-bootstrap.sh"

deploy_args=(
	--apps "${INFINITO_APPS}"
	--inventory-dir "${INFINITO_INVENTORY_DIR}"
	--debug
)

# Single init bakes the matrix folders with the inventory's default
# ASYNC_ENABLED (false). The async update pass runs as a per-round
# re-deploy with `-e ASYNC_ENABLED=true` overriding the host_var, so
# Pass 1 and Pass 2 always stay co-located on the SAME variant. The dev
# deploy wrapper handles that interleaving when `--full-cycle` is set
# (or `INFINITO_FULL_CYCLE=true` is exported, which we already inherit here).
echo ">>> init inventory (ASYNC_ENABLED=false, RUNTIME=dev baked)"
# RUNTIME MUST be `dev` here: the host process running this script lives
# OUTSIDE the development compose stack, so `detect_runtime()` falls back
# to "host". Without an explicit override the matrix-init step would bake
# `RUNTIME=host` into host_vars and the Playwright E2E gate
# (RUNTIME in [dev, act, github]) would never fire.
#
# Allow ad-hoc inventory overrides for dev iteration via `INIT_VARS_EXTRA`,
# e.g. `INIT_VARS_EXTRA='"SYSTEM_EMAIL_EXTERNAL": true'` to skip the local
# postfix relay in dev containers where systemd-postfix won't start.
INIT_VARS_BASE='"ASYNC_ENABLED": false, "RUNTIME": "dev"'
if [[ -n "${INIT_VARS_EXTRA:-}" ]]; then
	INIT_VARS="{${INIT_VARS_BASE}, ${INIT_VARS_EXTRA}}"
else
	INIT_VARS="{${INIT_VARS_BASE}}"
fi
"${PYTHON}" -m cli.administration.deploy.development init \
	--apps "${INFINITO_APPS}" \
	--inventory-dir "${INFINITO_INVENTORY_DIR}" \
	--vars "${INIT_VARS}"

if [[ "${INFINITO_FULL_CYCLE}" == "true" ]]; then
	echo ">>> deploy (PASS 1 sync + PASS 2 async per variant, INFINITO_FULL_CYCLE=true)"
	deploy_with_cache_retry "deploy-${INFINITO_APPS//[^A-Za-z0-9._-]/-}-full-cycle" -- \
		"${PYTHON}" -m cli.administration.deploy.development deploy \
		"${deploy_args[@]}" --full-cycle
else
	echo ">>> deploy (PASS 1 sync only, INFINITO_FULL_CYCLE=false)"
	deploy_with_cache_retry "deploy-${INFINITO_APPS//[^A-Za-z0-9._-]/-}" -- \
		"${PYTHON}" -m cli.administration.deploy.development deploy \
		"${deploy_args[@]}"
fi

echo
echo "✅ Done (no deletion)."
