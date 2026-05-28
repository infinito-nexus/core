#!/usr/bin/env bash
set -euo pipefail

# Update all apps using the already-initialized local inventory (no down/up, no purge).
#
# Required:
#   INFINITO_DISTRO   (arch|debian|ubuntu|fedora|centos)
#   INFINITO_DEPLOY_TYPE  (server|workstation|universal)
#   INFINITO_INVENTORY_DIR     (e.g. /etc/inventories/local-full-server)
#
# Optional:
#   INFINITO_LIMIT_HOST  (default: localhost)
#   INFINITO_DEBUG       (default: false)
#
# Notes:
# - This does NOT create the inventory. Run make compose-deploy apps=<role> first.
# - We recompute the app list to keep behavior deterministic with filters.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/tests/deploy/local/utils/lib.sh
source "${SCRIPT_DIR}/../../../utils/lib.sh"
# shellcheck source=scripts/tests/deploy/local/utils/cache-retry.sh
source "${SCRIPT_DIR}/../../../utils/cache-retry.sh"

REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../../.." && pwd)"
cd "${REPO_ROOT}"

: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (arch|debian|ubuntu|fedora|centos)}"
: "${INFINITO_DEPLOY_TYPE:?INFINITO_DEPLOY_TYPE must be set (server|workstation|universal)}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR must be set (e.g. /etc/inventories/local-full-server)}"

INFINITO_DEBUG="$(normalize_bool_or_default "${INFINITO_DEBUG:-}" false INFINITO_DEBUG)"

# When the previous matrix init produced one folder per round
# (`<INFINITO_INVENTORY_DIR>-0`, `<INFINITO_INVENTORY_DIR>-1`, ...), the
# `variant=<idx>` make arg pins this redeploy to the chosen round. Without
# `variant=` the unsuffixed path is used, which is correct for
# single-variant deploys (N=1).
inv_dir="${INFINITO_INVENTORY_DIR}"
if [[ -n "${variant:-}" ]]; then
	inv_dir="${inv_dir}-${variant}"
fi
inv_file="${inv_dir}/devices.yml"
pw_file="${inv_dir}/.password"

if [[ ! -f "${inv_file}" ]]; then
	echo "ERROR: inventory not found: ${inv_file}" >&2
	echo "Run: make compose-deploy apps=<role>" >&2
	exit 2
fi

if [[ ! -f "${pw_file}" ]]; then
	echo "ERROR: password file not found: ${pw_file}" >&2
	exit 2
fi

echo "=== local run (ALL apps) ==="
echo "distro        = ${INFINITO_DISTRO}"
echo "type          = ${INFINITO_DEPLOY_TYPE}"
echo "limit         = ${INFINITO_LIMIT_HOST}"
echo "debug         = ${INFINITO_DEBUG}"
echo "inventory_dir = ${inv_dir}"
echo "inv_file      = ${inv_file}"
echo

# Ensure stack is up
"${PYTHON}" -m cli.administration.deploy.development up \
	--when-down \
	--skip-entry-init

# Recompute apps list (optional, but keeps filters consistent)
apps_json="$(
	INFINITO_DEPLOY_TYPE="${INFINITO_DEPLOY_TYPE}" \
		INFINITO_WHITELIST="${INFINITO_WHITELIST:-}" \
		scripts/meta/resolve/apps.sh
)"

apps_count="$(
	"${PYTHON}" -c 'import json,sys; a=json.loads(sys.argv[1]); assert isinstance(a,list); print(len(a))' \
		"${apps_json}"
)"
if [[ "${apps_count}" == "0" ]]; then
	echo "ERROR: discovered apps list has length 0" >&2
	exit 2
fi

echo "apps_count=${apps_count}"
echo "apps_sample=$(
	"${PYTHON}" -c 'import json,sys; a=json.loads(sys.argv[1]); print(",".join(a[:8]) + ("..." if len(a)>8 else ""))' \
		"${apps_json}"
)"
echo

# Run deploy inside container
deploy_with_cache_retry "update-all" -- \
	"${PYTHON}" -m cli.administration.deploy.development exec \
	--env "INFINITO_INVENTORY_FILE=${inv_file}" \
	--env "INFINITO_INVENTORY_PASSWORD_FILE=${pw_file}" \
	--env "INFINITO_LIMIT_HOST=${INFINITO_LIMIT_HOST}" \
	--env "INFINITO_DEBUG=${INFINITO_DEBUG}" \
	-- bash "${INFINITO_SRC_DIR}/scripts/tests/deploy/local/deploy/container/update/all.sh"

echo
echo "✅ Local run finished."
