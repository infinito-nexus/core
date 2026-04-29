#!/usr/bin/env bash
set -euo pipefail

# Fresh-purged deploy: run exactly ONE app on ONE distro against the same stack.
# Same logic as CI version, but WITHOUT destructive cleanup.
#
# Required env:
#   INFINITO_DISTRO     arch|debian|ubuntu|fedora|centos
#   INVENTORY_DIR       /etc/inventories/local-full-server
#   TEST_DEPLOY_TYPE    server|workstation|universal
#   APPS                web-app-*
#
# Optional:
#   FULL_CYCLE=false    Default. Deploy only (pass 1). Set to 'true' to also run the update pass (pass 2).
#   PYTHON=python3
#   LIMIT_HOST=localhost

PYTHON="${PYTHON:-python3}"
FULL_CYCLE="${FULL_CYCLE:-false}"

: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (e.g. arch)}"
: "${INVENTORY_DIR:?INVENTORY_DIR must be set}"
: "${TEST_DEPLOY_TYPE:?TEST_DEPLOY_TYPE must be set (server|workstation|universal)}"
: "${APPS:?APPS must be set (e.g. web-app-keycloak)}"

LIMIT_HOST="${LIMIT_HOST:-localhost}"

case "${TEST_DEPLOY_TYPE}" in
server | workstation | universal) ;;
*)
	echo "[ERROR] Invalid TEST_DEPLOY_TYPE: ${TEST_DEPLOY_TYPE}" >&2
	exit 2
	;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
cd "${REPO_ROOT}"

echo "=== LOCAL: distro=${INFINITO_DISTRO} type=${TEST_DEPLOY_TYPE} app=${APPS} full_cycle=${FULL_CYCLE} ==="
echo "limit_host=${LIMIT_HOST}"
echo "inventory_dir=${INVENTORY_DIR}"
echo

echo ">>> Ensuring stack is up for distro ${INFINITO_DISTRO}"
"${PYTHON}" -m cli.deploy.development up \
	--when-down

echo ">>> Pre-cleanup shared entities (host docker context)"
APPS='matomo' scripts/tests/deploy/local/purge/entity.sh

echo ">>> Running entry.sh inside container"
"${PYTHON}" -m cli.deploy.development exec \
	-- bash /opt/src/infinito/scripts/tests/deploy/local/utils/entry-bootstrap.sh

deploy_args=(
	--apps "${APPS}"
	--inventory-dir "${INVENTORY_DIR}"
	--debug
)

# Single init bakes the matrix folders with the inventory's default
# ASYNC_ENABLED (false). The async update pass runs as a per-round
# re-deploy with `-e ASYNC_ENABLED=true` overriding the host_var, so
# Pass 1 and Pass 2 always stay co-located on the SAME variant. The dev
# deploy wrapper handles that interleaving when `--full-cycle` is set
# (or `FULL_CYCLE=true` is exported, which we already inherit here).
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
"${PYTHON}" -m cli.deploy.development init \
	--apps "${APPS}" \
	--inventory-dir "${INVENTORY_DIR}" \
	--vars "${INIT_VARS}"

if [[ "${FULL_CYCLE}" == "true" ]]; then
	echo ">>> deploy (PASS 1 sync + PASS 2 async per variant, FULL_CYCLE=true)"
	"${PYTHON}" -m cli.deploy.development deploy "${deploy_args[@]}" --full-cycle
else
	echo ">>> deploy (PASS 1 sync only, FULL_CYCLE=false)"
	"${PYTHON}" -m cli.deploy.development deploy "${deploy_args[@]}"
fi

echo
echo "✅ Done (no deletion)."
