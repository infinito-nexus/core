#!/usr/bin/env bash
# In-container half of `make compose-deploy mode=update apps=…`.
#
# Mirrors the host wrapper at deploy/apps/update/selection.sh; called
# via `docker exec`, which injects the env-vars asserted below. The
# repo is mounted at ${INFINITO_SRC_DIR} by the dev compose stack.
#
# Required env:
#   INFINITO_INVENTORY_FILE   absolute path to <inv>/devices.yml
#   apps    space-separated app id list for `--id`
#   INFINITO_DEBUG   "true"|"false" — appends `--debug` when true
#   INFINITO_SRC_DIR absolute path to the bind-mounted repo root in the container
set -euo pipefail
: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR must be set by the container environment}"
cd "${INFINITO_SRC_DIR}"

: "${INFINITO_INVENTORY_FILE:?INFINITO_INVENTORY_FILE must be set}"
: "${apps:?apps must be set}"
: "${INFINITO_DEBUG:?INFINITO_DEBUG must be set}"

inv_dir="$(dirname "${INFINITO_INVENTORY_FILE}")"
pw_file="${inv_dir}/.password"

if [[ ! -f "${INFINITO_INVENTORY_FILE}" ]]; then
	echo "ERROR: inventory not found: ${INFINITO_INVENTORY_FILE}" >&2
	parent_dir="$(dirname "${inv_dir}")"
	if [[ -d "${parent_dir}" ]]; then
		shopt -s nullglob
		suggestions=()
		for sibling in "${parent_dir}"/*/devices.yml; do
			[[ "${sibling}" != "${INFINITO_INVENTORY_FILE}" ]] && suggestions+=("${sibling}")
		done
		shopt -u nullglob
		if ((${#suggestions[@]} > 0)); then
			echo "Did you mean one of:" >&2
			printf '  - %s\n' "${suggestions[@]}" >&2
		fi
	fi
	exit 2
fi

if [[ ! -f "${pw_file}" ]]; then
	echo "ERROR: password file not found: ${pw_file}" >&2
	exit 2
fi

echo ">>> Running entry.sh"
./scripts/docker/entry.sh true

echo ">>> Starting rapid deploy"
# `--id` accepts multiple positional ids; split apps on whitespace into a
# proper array instead of relying on shell word-splitting at expansion time
# (which shellcheck SC2206 rightly flags as fragile).
read -ra app_ids <<<"${apps}"
cmd=(infinito administration deploy dedicated "${INFINITO_INVENTORY_FILE}"
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

if [[ "${INFINITO_DEBUG}" == "true" ]]; then
	cmd+=(--debug)
fi

exec "${cmd[@]}"
