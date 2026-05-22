#!/usr/bin/env bash
# In-container half of `make compose-deploy mode=update`.
#
# Mirrors the host wrapper at deploy/apps/update/all.sh; called via
# `cli.administration.deploy.development exec --env KEY=VAL`, which
# injects the env-vars asserted below. The repo is mounted at
# ${INFINITO_SRC_DIR} by the dev compose stack.
#
# Required env:
#   INFINITO_INVENTORY_FILE   absolute path to <inv>/devices.yml
#   INFINITO_INVENTORY_PASSWORD_FILE                   absolute path to <inv>/.password
#   INFINITO_LIMIT_HOST       Ansible limit (typically "localhost")
#   INFINITO_DEBUG            "true"|"false" — appends `--debug` when true
#   INFINITO_SRC_DIR          absolute path to the bind-mounted repo root in the container
set -euo pipefail
: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR must be set by the container environment}"
cd "${INFINITO_SRC_DIR}"

: "${INFINITO_INVENTORY_FILE:?INFINITO_INVENTORY_FILE must be set}"
: "${INFINITO_INVENTORY_PASSWORD_FILE:?INFINITO_INVENTORY_PASSWORD_FILE must be set}" # nocheck: driver-injected-per-invocation
: "${INFINITO_LIMIT_HOST:?INFINITO_LIMIT_HOST must be set}"
: "${INFINITO_DEBUG:?INFINITO_DEBUG must be set}"

echo ">>> entry.sh bootstrap"
./scripts/docker/entry.sh true

cmd=(infinito administration deploy dedicated "${INFINITO_INVENTORY_FILE}"
	--skip-backup
	--skip-cleanup
	-l "${INFINITO_LIMIT_HOST}"
	--diff
	-vv
	--password-file "${INFINITO_INVENTORY_PASSWORD_FILE}" # nocheck: driver-injected-per-invocation
	-e ASYNC_ENABLED=false
	-e SYS_SERVICE_ALL_ENABLED=false
	-e SYS_SERVICE_DEFAULT_STATE=started
)

if [[ "${INFINITO_DEBUG}" == "true" ]]; then
	cmd+=(--debug)
fi

echo ">>> running:"
printf ' %q' "${cmd[@]}"
echo

exec "${cmd[@]}"
