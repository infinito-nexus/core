#!/usr/bin/env bash
set -euo pipefail

# Update a selection of apps inside the running infinito container (reuses inventory, no down/up).
# Expects (ALL required):
#   apps      e.g. web-app-nextcloud
#   INFINITO_DEPLOY_TYPE   server|workstation|universal
#   INFINITO_CONTAINER e.g. infinito_nexus_arch
#   INFINITO_DEBUG     true|false
#   INFINITO_INVENTORY_DIR      e.g. /etc/inventories/local-full-server

: "${apps:?apps is not set (e.g. apps=web-app-nextcloud)}"
: "${INFINITO_DEPLOY_TYPE:?INFINITO_DEPLOY_TYPE is not set (server|workstation|universal)}"
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set (e.g. infinito_nexus_arch)}"
: "${INFINITO_DEBUG:?INFINITO_DEBUG is not set (true|false)}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR is not set (e.g. INFINITO_INVENTORY_DIR=/etc/inventories/local-full-server)}"
: "${INFINITO_INVENTORY_FILE:?INFINITO_INVENTORY_FILE is not set — source scripts/meta/env/load.sh first}"

# When the previous matrix init produced one folder per round
# (`<INFINITO_INVENTORY_DIR>-0`, `<INFINITO_INVENTORY_DIR>-1`, ...), the
# `variant=<idx>` make arg pins this redeploy to the chosen round so the
# operator can iterate one specific variant without re-running the full
# matrix. Without `variant=` the unsuffixed path is used, which is
# correct for single-variant deploys (N=1). See docs/contributing/design/variants.md.
if [[ -n "${variant:-}" ]]; then
	INFINITO_INVENTORY_DIR="${INFINITO_INVENTORY_DIR}-${variant}"
	INFINITO_INVENTORY_FILE="${INFINITO_INVENTORY_DIR}/devices.yml"
fi

case "${INFINITO_DEPLOY_TYPE}" in
server | workstation | universal) ;;
*)
	echo "Invalid INFINITO_DEPLOY_TYPE: ${INFINITO_DEPLOY_TYPE}" >&2
	echo "Allowed: server | workstation | universal" >&2
	exit 2
	;;
esac

case "${INFINITO_DEBUG}" in
true | false) ;;
*)
	echo "Invalid INFINITO_DEBUG: ${INFINITO_DEBUG}" >&2
	echo "Allowed: true | false" >&2
	exit 2
	;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../../.." && pwd)"

# shellcheck source=scripts/tests/deploy/local/utils/cache-retry.sh
source "${SCRIPT_DIR}/../../../utils/cache-retry.sh"

echo "=== rapid deploy: type=${INFINITO_DEPLOY_TYPE} app=${apps} container=${INFINITO_CONTAINER} debug=${INFINITO_DEBUG} ==="
echo "inventory_dir=${INFINITO_INVENTORY_DIR}"

deploy_with_cache_retry "update-${apps//[^A-Za-z0-9._-]/-}" -- \
	docker exec \
	-e disable="${disable:-}" \
	-e INFINITO_INVENTORY_FILE="${INFINITO_INVENTORY_FILE}" \
	-e apps="${apps}" \
	-e INFINITO_DEBUG="${INFINITO_DEBUG}" \
	"${INFINITO_CONTAINER}" \
	bash "${INFINITO_SRC_DIR}/scripts/tests/deploy/local/deploy/container/update/selection.sh"
