#!/usr/bin/env bash
# In-container half of `make compose-deploy` (initialize all discovered apps).
#
# Mirrors the host wrapper at deploy/apps/initialize/all.sh; called via
# `cli.administration.deploy.development exec --env KEY=VAL`, which
# injects the env-vars asserted below. Performs entry bootstrap, creates
# the inventory and runs the dedicated deploy in one in-container
# session. The repo is mounted at ${INFINITO_SRC_DIR} by the dev compose
# stack.
#
# Required env:
#   INFINITO_INVENTORY_DIR    absolute base inventory dir (no trailing slash)
#   INFINITO_INVENTORY_FILE   absolute path to <INFINITO_INVENTORY_DIR>/devices.yml
#   INFINITO_INVENTORY_VARS_FILE       repo-relative dev vars file (SPOT)
#   APPS_CSV                  comma-separated app id list for `--include`
#   APPS_COUNT                length of APPS_CSV (echoed for log clarity)
#   INFINITO_LIMIT_HOST       Ansible host (typically "localhost")
#   INFINITO_SRC_DIR          absolute path to the bind-mounted repo root in the container
#   RUNTIME_VARS_JSON         JSON object passed verbatim to `--vars`
set -euo pipefail
: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR must be set by the container environment}"
cd "${INFINITO_SRC_DIR}"

: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR must be set}"
: "${INFINITO_INVENTORY_FILE:?INFINITO_INVENTORY_FILE must be set}"
: "${INFINITO_INVENTORY_VARS_FILE:?INFINITO_INVENTORY_VARS_FILE must be set}"
: "${APPS_CSV:?APPS_CSV must be set}"
: "${APPS_COUNT:?APPS_COUNT must be set}"
: "${INFINITO_LIMIT_HOST:?INFINITO_LIMIT_HOST must be set}"
: "${RUNTIME_VARS_JSON:?RUNTIME_VARS_JSON must be set}"

inv_dir="${INFINITO_INVENTORY_DIR}"
pw_file="${inv_dir}/.password"

echo ">>> Running entry.sh bootstrap"
./scripts/docker/entry.sh true

mkdir -p "${inv_dir}"

if [[ ! -f "${pw_file}" ]]; then
	printf '%s\n' 'local-vault-password' >"${pw_file}"
	chmod 600 "${pw_file}" || true
fi

echo ">>> Creating inventory at ${INFINITO_INVENTORY_FILE}"
echo ">>> Include apps (${APPS_COUNT}): ${APPS_CSV}"

infinito administration inventory provision "${inv_dir}" \
	--inventory-file "${INFINITO_INVENTORY_FILE}" \
	--host "${INFINITO_LIMIT_HOST}" \
	--vars "${RUNTIME_VARS_JSON}" \
	--vars-file "${INFINITO_INVENTORY_VARS_FILE}" \
	--include "${APPS_CSV}"

echo ">>> Deploying against ${INFINITO_INVENTORY_FILE}"

infinito administration deploy dedicated "${INFINITO_INVENTORY_FILE}" \
	--skip-backup \
	--debug \
	--log "${INFINITO_SRC_DIR}/logs" \
	-l "${INFINITO_LIMIT_HOST}" \
	--diff \
	-vv \
	--password-file "${pw_file}"
