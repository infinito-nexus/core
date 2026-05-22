#!/usr/bin/env bash
set -euo pipefail

# Initialize all discovered apps: fresh inventory, no entity purge, stack kept on disk.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/tests/deploy/local/utils/cache-retry.sh
source "${SCRIPT_DIR}/../../../utils/cache-retry.sh"

# ---------------------------------------------------------------------------
# Required environment
# ---------------------------------------------------------------------------
: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (arch|debian|ubuntu|fedora|centos)}"
: "${INFINITO_DEPLOY_TYPE:?INFINITO_DEPLOY_TYPE must be set (server|workstation|universal)}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR must be set (e.g. /etc/inventories/local-full-server)}"
: "${INFINITO_INVENTORY_FILE:?INFINITO_INVENTORY_FILE is not set — source scripts/meta/env/load.sh first}"
: "${INFINITO_INVENTORY_VARS_FILE:?INFINITO_INVENTORY_VARS_FILE is not set — source scripts/meta/env/load.sh first}"

# Optional overrides
INFINITO_WHITELIST="${INFINITO_WHITELIST:-}"

# This script always generates inventories for the development compose stack.
RUNTIME_VARS_JSON='{"RUNTIME":"dev"}'

echo "=== local full deploy (development compose stack) ==="
echo "distro        = ${INFINITO_DISTRO}"
echo "type          = ${INFINITO_DEPLOY_TYPE}"
echo "limit         = ${INFINITO_LIMIT_HOST}"
echo "inventory_dir = ${INFINITO_INVENTORY_DIR}"
echo "whitelist     = ${INFINITO_WHITELIST}"
echo

# ---------------------------------------------------------------------------
# 1) Bring up development stack (no build) on host
# ---------------------------------------------------------------------------
echo ">>> Starting development compose stack (no build)"
"${PYTHON}" -m cli.administration.deploy.development up \
	--skip-entry-init

# ---------------------------------------------------------------------------
# 2) Discover apps on HOST (needs docker compose)
# ---------------------------------------------------------------------------
echo ">>> Discovering apps on host via scripts/meta/resolve/apps.sh (INFINITO_DEPLOY_TYPE=${INFINITO_DEPLOY_TYPE})"

# IMPORTANT:
# - compose can emit warnings on STDOUT (depending on version/config)
# - we must guarantee JSON-only output for downstream parsing
# - PYTHON from host venv must NOT be used inside container exec calls
discover_out="$(
	set +e
	INFINITO_DEPLOY_TYPE="${INFINITO_DEPLOY_TYPE}" \
		INFINITO_WHITELIST="${INFINITO_WHITELIST}" \
		PYTHON=python3 \
		scripts/meta/resolve/apps.sh 2> >(cat >&2) |
		jq -c 'if type=="array" then . else [] end' 2>/dev/null
	echo "rc=$?" >&2
)"
# Now discover_out should be compact JSON array or empty.

if [[ -z "${discover_out}" ]]; then
	echo "ERROR: apps discovery produced empty output" >&2
	echo "DEBUG: raw apps.sh output (first 50 lines):" >&2
	INFINITO_DEPLOY_TYPE="${INFINITO_DEPLOY_TYPE}" INFINITO_WHITELIST="${INFINITO_WHITELIST}" PYTHON=python3 \
		scripts/meta/resolve/apps.sh 2>&1 | sed -n '1,50p' >&2
	exit 2
fi

apps_json="${discover_out}"
echo "apps_json=${apps_json}"

# Validate JSON list + compute count
apps_count="$(
	"${PYTHON}" -c 'import json,sys; a=json.loads(sys.argv[1]); assert isinstance(a,list); print(len(a))' \
		"${apps_json}"
)"

if [[ "${apps_count}" == "0" ]]; then
	echo "ERROR: discovered apps list has length 0"
	exit 2
fi

# Convert JSON list -> CSV
apps_csv="$(
	"${PYTHON}" -c 'import json,sys; a=json.loads(sys.argv[1]); print(",".join(map(str,a)))' \
		"${apps_json}"
)"

if [[ -z "${apps_csv}" ]]; then
	echo "ERROR: apps_csv ended up empty even though apps_count=${apps_count}"
	echo "----- apps_json -----"
	printf '%s\n' "${apps_json}"
	echo "---------------------"
	exit 2
fi

echo "apps_count=${apps_count}"
echo

# ---------------------------------------------------------------------------
# 3) entry.sh + create inventory + deploy INSIDE container via development exec
# ---------------------------------------------------------------------------
echo ">>> Running entry/init + inventory + deploy inside infinito container via development exec"

deploy_with_cache_retry "initialize-all" -- \
	"${PYTHON}" -m cli.administration.deploy.development exec \
	--env "INFINITO_INVENTORY_DIR=${INFINITO_INVENTORY_DIR}" \
	--env "INFINITO_INVENTORY_FILE=${INFINITO_INVENTORY_FILE}" \
	--env "INFINITO_INVENTORY_VARS_FILE=${INFINITO_INVENTORY_VARS_FILE}" \
	--env "APPS_CSV=${apps_csv}" \
	--env "APPS_COUNT=${apps_count}" \
	--env "INFINITO_LIMIT_HOST=${INFINITO_LIMIT_HOST}" \
	--env "RUNTIME_VARS_JSON=${RUNTIME_VARS_JSON}" \
	-- bash "${INFINITO_SRC_DIR}/scripts/tests/deploy/local/deploy/container/initialize/all.sh"

echo
echo "=== local full deploy finished ==="
