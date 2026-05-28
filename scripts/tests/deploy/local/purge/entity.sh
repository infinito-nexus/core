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

: "${apps:?apps is not set (e.g. apps=web-app-nextcloud)}"
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set (e.g. infinito_nexus_arch)}"

echo "=== local cleanup: apps=${apps} container=${INFINITO_CONTAINER} ==="

: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR is not set; source scripts/meta/env/load.sh}"

docker exec -e apps="${apps}" "${INFINITO_CONTAINER}" \
	bash "${INFINITO_SRC_DIR}/scripts/container/purge/apps.sh"
