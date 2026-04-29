#!/usr/bin/env bash
set -euo pipefail

# Reuse-kept deploy for a single app inside the running infinito container.
# Expects (ALL required):
#   APPS               e.g. web-app-nextcloud
#   TEST_DEPLOY_TYPE   server|workstation|universal
#   INFINITO_CONTAINER e.g. infinito_nexus_arch
#   DEBUG              true|false
#   INVENTORY_DIR      e.g. /etc/inventories/local-full-server

: "${APPS:?APPS is not set (e.g. APPS=web-app-nextcloud)}"
: "${TEST_DEPLOY_TYPE:?TEST_DEPLOY_TYPE is not set (server|workstation|universal)}"
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set (e.g. infinito_nexus_arch)}"
: "${DEBUG:?DEBUG is not set (true|false)}"
: "${INVENTORY_DIR:?INVENTORY_DIR is not set (e.g. INVENTORY_DIR=/etc/inventories/local-full-server)}"
: "${INVENTORY_FILE:?INVENTORY_FILE is not set — source scripts/meta/env/inventory.sh first}"

# When the previous matrix init produced one folder per round
# (`<INVENTORY_DIR>-0`, `<INVENTORY_DIR>-1`, ...), `VARIANT=<idx>` pins
# this redeploy to the chosen round so the operator can iterate one
# specific variant without re-running the full matrix. Without VARIANT
# the unsuffixed path is used, which is correct for single-variant
# deploys (N=1). See docs/contributing/design/variants.md.
if [[ -n "${VARIANT:-}" ]]; then
	INVENTORY_DIR="${INVENTORY_DIR}-${VARIANT}"
	INVENTORY_FILE="${INVENTORY_DIR}/devices.yml"
fi

case "${TEST_DEPLOY_TYPE}" in
server | workstation | universal) ;;
*)
	echo "Invalid TEST_DEPLOY_TYPE: ${TEST_DEPLOY_TYPE}" >&2
	echo "Allowed: server | workstation | universal" >&2
	exit 2
	;;
esac

case "${DEBUG}" in
true | false) ;;
*)
	echo "Invalid DEBUG: ${DEBUG}" >&2
	echo "Allowed: true | false" >&2
	exit 2
	;;
esac

echo "=== rapid deploy: type=${TEST_DEPLOY_TYPE} app=${APPS} container=${INFINITO_CONTAINER} debug=${DEBUG} ==="
echo "inventory_dir=${INVENTORY_DIR}"

docker exec \
	-e SERVICES_DISABLED="${SERVICES_DISABLED:-}" \
	-e INVENTORY_FILE="${INVENTORY_FILE}" \
	-e APPS="${APPS}" \
	-e DEBUG="${DEBUG}" \
	"${INFINITO_CONTAINER}" \
	bash /opt/src/infinito/scripts/tests/deploy/local/utils/reuse-kept-app-deploy.sh
