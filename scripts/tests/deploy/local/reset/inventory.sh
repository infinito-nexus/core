#!/usr/bin/env bash
set -euo pipefail

# Initialize a local inventory for ALL discovered apps.
#
# Required:
#   INFINITO_DISTRO   (arch|debian|ubuntu|fedora|centos)
#   TEST_DEPLOY_TYPE  (server|workstation|universal)
#   INVENTORY_DIR     (e.g. /etc/inventories/local-full-server)

: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (arch|debian|ubuntu|fedora|centos)}"
: "${TEST_DEPLOY_TYPE:?TEST_DEPLOY_TYPE must be set (server|workstation|universal)}"
: "${INVENTORY_DIR:?INVENTORY_DIR must be set (e.g. /etc/inventories/local-full-server)}"
: "${INVENTORY_FILE:?INVENTORY_FILE is not set — source scripts/meta/env/inventory.sh first}"
: "${INVENTORY_VARS_FILE:?INVENTORY_VARS_FILE is not set — source scripts/meta/env/inventory.sh first}"

# This script always generates inventories for the development compose stack.
RUNTIME_VARS_JSON='{"RUNTIME":"dev","SYS_SERVICE_RUNNER_RETRIES":1}'

echo "=== local inventory init (ALL apps) ==="
echo "distro        = ${INFINITO_DISTRO}"
echo "type          = ${TEST_DEPLOY_TYPE}"
echo "inventory_dir = ${INVENTORY_DIR}"
echo

# 1) Bring up development stack (no build)
echo ">>> Starting development compose stack (no build)"
"${PYTHON}" -m cli.deploy.development up \
	--skip-entry-init

# 2) Discover apps on HOST (same as local/deploy/fresh-kept-all.sh)
apps_json="$(
	TEST_DEPLOY_TYPE="${TEST_DEPLOY_TYPE}" \
		WHITELIST="${WHITELIST:-}" \
		PYTHON=python3 \
		scripts/meta/resolve/apps.sh
)"

if [[ -z "${apps_json}" ]]; then
	echo "ERROR: app matrix is empty" >&2
	exit 2
fi

apps_count="$(
	"${PYTHON}" -c 'import json,sys; a=json.loads(sys.argv[1]); assert isinstance(a,list); print(len(a))' \
		"${apps_json}"
)"

if [[ "${apps_count}" == "0" ]]; then
	echo "ERROR: discovered apps list has length 0" >&2
	echo "apps_json=${apps_json}" >&2
	exit 2
fi

apps_csv="$(
	"${PYTHON}" -c 'import json,sys; a=json.loads(sys.argv[1]); print(",".join(map(str,a)))' \
		"${apps_json}"
)"

if [[ -z "${apps_csv}" ]]; then
	echo "ERROR: apps_csv ended up empty even though apps_count=${apps_count}" >&2
	exit 2
fi

echo "apps_count=${apps_count}"
echo "apps_sample=$(
	"${PYTHON}" -c 'import json,sys; a=json.loads(sys.argv[1]); print(",".join(a[:8]) + ("..." if len(a)>8 else ""))' \
		"${apps_json}"
)"
echo

# 3) Run entry.sh + create inventory INSIDE container
echo ">>> Initializing inventory inside container"

"${PYTHON}" -m cli.deploy.development exec \
	-- \
	bash -c "
    set -euo pipefail
    cd /opt/src/infinito

    echo '>>> entry.sh bootstrap'
    ./scripts/docker/entry.sh true

    inv_dir='${INVENTORY_DIR}'
    INVENTORY_FILE='${INVENTORY_FILE}'
    pw_file=\"\${inv_dir}/.password\"
    echo \">>> Reset inventory dir \${inv_dir}\"
    rm -rf \"\${inv_dir}\"
    mkdir -p \"\${inv_dir}\"

    if [[ ! -f \"\${pw_file}\" ]]; then
      printf '%s\n' 'local-vault-password' > \"\${pw_file}\"
      chmod 600 \"\${pw_file}\" || true
    fi

    echo \">>> Creating inventory at \${INVENTORY_FILE}\"
    infinito create inventory \"\${inv_dir}\" \
      --inventory-file \"\${INVENTORY_FILE}\" \
      --vars '${RUNTIME_VARS_JSON}' \
      --host 'localhost' \
      --ssl-disabled \
      --vars-file '${INVENTORY_VARS_FILE}' \
      --include '${apps_csv}'

    echo '✅ Inventory initialized.'
  "

echo
echo "✅ Local inventory init finished."
echo "Inventory: ${INVENTORY_FILE}"
