#!/usr/bin/env bash
# In-container helper for `make deploy-reuse-kept-all`.
#
# Called from the host wrapper at
# scripts/tests/deploy/local/deploy/reuse-kept-all.sh via
# `cli.deploy.development exec --env KEY=VAL`, which injects the env-vars
# asserted below. The repo is mounted at /opt/src/infinito by the dev
# compose stack.
#
# Required env:
#   INVENTORY_FILE   absolute path to <inv>/devices.yml
#   PW_FILE          absolute path to <inv>/.password
#   LIMIT_HOST       Ansible limit (typically "localhost")
#   DEBUG            "true"|"false" — appends `--debug` when true
set -euo pipefail
cd /opt/src/infinito

: "${INVENTORY_FILE:?INVENTORY_FILE must be set}"
: "${PW_FILE:?PW_FILE must be set}"
: "${LIMIT_HOST:?LIMIT_HOST must be set}"
: "${DEBUG:?DEBUG must be set}"

echo ">>> entry.sh bootstrap"
./scripts/docker/entry.sh true

cmd=(infinito deploy dedicated "${INVENTORY_FILE}"
	--skip-backup
	--skip-cleanup
	-l "${LIMIT_HOST}"
	--diff
	-vv
	--password-file "${PW_FILE}"
	-e ASYNC_ENABLED=false
	-e SYS_SERVICE_ALL_ENABLED=false
	-e SYS_SERVICE_DEFAULT_STATE=started
)

if [[ "${DEBUG}" == "true" ]]; then
	cmd+=(--debug)
fi

echo ">>> running:"
printf ' %q' "${cmd[@]}"
echo

exec "${cmd[@]}"
