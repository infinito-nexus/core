#!/usr/bin/env bash
# In-container helper for `make deploy-fresh-kept-all`.
#
# Called from the host wrapper at
# scripts/tests/deploy/local/deploy/fresh-kept-all.sh via
# `cli.deploy.development exec --env KEY=VAL`, which injects the env-vars
# asserted below. Performs entry bootstrap, creates the inventory and
# runs the dedicated deploy in one in-container session. The repo is
# mounted at /opt/src/infinito by the dev compose stack.
#
# Required env:
#   INVENTORY_DIR        absolute base inventory dir (no trailing slash)
#   INVENTORY_FILE       absolute path to <INVENTORY_DIR>/devices.yml
#   INVENTORY_VARS_FILE  repo-relative dev vars file (SPOT)
#   APPS_CSV             comma-separated app id list for `--include`
#   APPS_COUNT           length of APPS_CSV (echoed for log clarity)
#   LIMIT_HOST           Ansible host (typically "localhost")
#   RUNTIME_VARS_JSON    JSON object passed verbatim to `--vars`
set -euo pipefail
cd /opt/src/infinito

: "${INVENTORY_DIR:?INVENTORY_DIR must be set}"
: "${INVENTORY_FILE:?INVENTORY_FILE must be set}"
: "${INVENTORY_VARS_FILE:?INVENTORY_VARS_FILE must be set}"
: "${APPS_CSV:?APPS_CSV must be set}"
: "${APPS_COUNT:?APPS_COUNT must be set}"
: "${LIMIT_HOST:?LIMIT_HOST must be set}"
: "${RUNTIME_VARS_JSON:?RUNTIME_VARS_JSON must be set}"

inv_dir="${INVENTORY_DIR}"
pw_file="${inv_dir}/.password"

echo ">>> Running entry.sh bootstrap"
./scripts/docker/entry.sh true

mkdir -p "${inv_dir}"

if [[ ! -f "${pw_file}" ]]; then
	printf '%s\n' 'local-vault-password' >"${pw_file}"
	chmod 600 "${pw_file}" || true
fi

echo ">>> Creating inventory at ${INVENTORY_FILE}"
echo ">>> Include apps (${APPS_COUNT}): ${APPS_CSV}"

infinito create inventory "${inv_dir}" \
	--inventory-file "${INVENTORY_FILE}" \
	--host "${LIMIT_HOST}" \
	--ssl-disabled \
	--vars "${RUNTIME_VARS_JSON}" \
	--vars-file "${INVENTORY_VARS_FILE}" \
	--include "${APPS_CSV}"

echo ">>> Deploying against ${INVENTORY_FILE}"

infinito deploy dedicated "${INVENTORY_FILE}" \
	--skip-backup \
	--debug \
	--log /opt/src/infinito/logs \
	-l "${LIMIT_HOST}" \
	--diff \
	-vv \
	--password-file "${pw_file}"
