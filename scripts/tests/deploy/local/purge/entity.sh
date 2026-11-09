#!/usr/bin/env bash
set -euo pipefail

# Cleanup one or multiple app entities in the running infinito container.
#
# Expects:
#   apps      (required)
#     Examples:
#       apps=web-app-nextcloud
#       apps="web-app-nextcloud web-app-keycloak"
#       apps="web-app-nextcloud,web-app-keycloak"
#
#   INFINITO_CONTAINER (required)
#     Example:
#       infinito_nexus_arch
#
#   retire    (optional)
#     Non-empty also drops the apps from every round inventory under
#     INFINITO_INVENTORY_DIR, which is then required.

: "${apps:?apps is not set (e.g. apps=web-app-nextcloud)}"
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set (e.g. infinito_nexus_arch)}"

echo "=== local cleanup: apps=${apps} container=${INFINITO_CONTAINER} ==="

: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR is not set; source scripts/meta/env/load.sh}"

exec_env=(-e apps="${apps}")
if [[ -n "${retire:-}" ]]; then
	: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR is not set; source scripts/meta/env/load.sh}"
	exec_env+=(-e retire="${retire}" -e INFINITO_INVENTORY_DIR="${INFINITO_INVENTORY_DIR}")
fi

docker exec "${exec_env[@]}" "${INFINITO_CONTAINER}" \
	bash "${INFINITO_SRC_DIR}/scripts/container/purge/apps.sh"
