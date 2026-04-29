#!/usr/bin/env bash
# In-container helper for `make deploy-reuse-kept-apps`.
#
# Called from the host wrapper at
# scripts/tests/deploy/local/deploy/reuse-kept-app.sh via `docker exec`,
# which is responsible for injecting the env-vars asserted below. The
# repo is mounted at /opt/src/infinito by the dev compose stack.
#
# Required env:
#   INVENTORY_FILE   absolute path to <inv>/devices.yml
#   APPS             space-separated app id list for `--id`
#   DEBUG            "true"|"false" — appends `--debug` when true
set -euo pipefail
cd /opt/src/infinito

: "${INVENTORY_FILE:?INVENTORY_FILE must be set}"
: "${APPS:?APPS must be set}"
: "${DEBUG:?DEBUG must be set}"

inv_dir="$(dirname "${INVENTORY_FILE}")"
pw_file="${inv_dir}/.password"

if [[ ! -f "${INVENTORY_FILE}" ]]; then
	echo "ERROR: inventory not found: ${INVENTORY_FILE}" >&2
	exit 2
fi

if [[ ! -f "${pw_file}" ]]; then
	echo "ERROR: password file not found: ${pw_file}" >&2
	exit 2
fi

echo ">>> Running entry.sh"
./scripts/docker/entry.sh true

echo ">>> Starting rapid deploy"
# `--id` accepts multiple positional ids; split APPS on whitespace into a
# proper array instead of relying on shell word-splitting at expansion time
# (which shellcheck SC2206 rightly flags as fragile).
read -ra app_ids <<<"${APPS}"
cmd=(infinito deploy dedicated "${INVENTORY_FILE}"
	--skip-backup
	--skip-cleanup
	--id "${app_ids[@]}"
	-l localhost
	--diff
	-vv
	--password-file "${pw_file}"
	-e ASYNC_ENABLED=false
	-e SYS_SERVICE_ALL_ENABLED=false
	-e SYS_SERVICE_DEFAULT_STATE=started
)

if [[ "${DEBUG}" == "true" ]]; then
	cmd+=(--debug)
fi

exec "${cmd[@]}"
