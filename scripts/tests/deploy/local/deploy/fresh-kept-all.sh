#!/usr/bin/env bash
set -euo pipefail

# Fresh-kept deploy for all discovered apps.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
cd "${REPO_ROOT}"

# ---------------------------------------------------------------------------
# Required environment
# ---------------------------------------------------------------------------
: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (arch|debian|ubuntu|fedora|centos)}"
: "${TEST_DEPLOY_TYPE:?TEST_DEPLOY_TYPE must be set (server|workstation|universal)}"
: "${INVENTORY_DIR:?INVENTORY_DIR must be set (e.g. /etc/inventories/local-full-server)}"
: "${INVENTORY_FILE:?INVENTORY_FILE is not set — source scripts/meta/env/inventory.sh first}"
: "${INVENTORY_VARS_FILE:?INVENTORY_VARS_FILE is not set — source scripts/meta/env/inventory.sh first}"

# Optional overrides
LIMIT_HOST="${LIMIT_HOST:-localhost}"
WHITELIST="${WHITELIST:-}"

# This script always generates inventories for the development compose stack.
RUNTIME_VARS_JSON='{"RUNTIME":"dev"}'

echo "=== local full deploy (development compose stack) ==="
echo "distro        = ${INFINITO_DISTRO}"
echo "type          = ${TEST_DEPLOY_TYPE}"
echo "limit         = ${LIMIT_HOST}"
echo "inventory_dir = ${INVENTORY_DIR}"
echo "whitelist     = ${WHITELIST}"
echo

# ---------------------------------------------------------------------------
# 1) Bring up development stack (no build) on host
# ---------------------------------------------------------------------------
echo ">>> Starting development compose stack (no build)"
"${PYTHON}" -m cli.deploy.development up \
	--skip-entry-init

# ---------------------------------------------------------------------------
# 2) Discover apps on HOST (needs docker compose)
# ---------------------------------------------------------------------------
echo ">>> Discovering apps on host via scripts/meta/resolve/apps.sh (TEST_DEPLOY_TYPE=${TEST_DEPLOY_TYPE})"

# IMPORTANT:
# - compose can emit warnings on STDOUT (depending on version/config)
# - we must guarantee JSON-only output for downstream parsing
# - PYTHON from host venv must NOT be used inside container exec calls
discover_out="$(
	set +e
	TEST_DEPLOY_TYPE="${TEST_DEPLOY_TYPE}" \
		WHITELIST="${WHITELIST}" \
		PYTHON=python3 \
		scripts/meta/resolve/apps.sh 2> >(cat >&2) |
		jq -c 'if type=="array" then . else [] end' 2>/dev/null
	echo "rc=$?" >&2
)"
# Now discover_out should be compact JSON array or empty.

if [[ -z "${discover_out}" ]]; then
	echo "ERROR: apps discovery produced empty output" >&2
	echo "DEBUG: raw apps.sh output (first 50 lines):" >&2
	TEST_DEPLOY_TYPE="${TEST_DEPLOY_TYPE}" WHITELIST="${WHITELIST}" PYTHON=python3 \
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

"${PYTHON}" -m cli.deploy.development exec \
	--env "INVENTORY_DIR=${INVENTORY_DIR}" \
	--env "INVENTORY_FILE=${INVENTORY_FILE}" \
	--env "INVENTORY_VARS_FILE=${INVENTORY_VARS_FILE}" \
	--env "APPS_CSV=${apps_csv}" \
	--env "APPS_COUNT=${apps_count}" \
	--env "LIMIT_HOST=${LIMIT_HOST}" \
	--env "RUNTIME_VARS_JSON=${RUNTIME_VARS_JSON}" \
	-- bash /opt/src/infinito/scripts/tests/deploy/local/utils/fresh-kept-all-init-and-deploy.sh

echo
echo "=== local full deploy finished ==="
