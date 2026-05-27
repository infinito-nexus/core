#!/usr/bin/env bash
set -euo pipefail

# Cleanup one or multiple app entities in the running infinito container.
#
# Expects:
#   INFINITO_APPS      (required)
#     Examples:
#       INFINITO_APPS=web-app-nextcloud
#       INFINITO_APPS="web-app-nextcloud web-app-keycloak"
#       INFINITO_APPS="web-app-nextcloud,web-app-keycloak"
#
#   INFINITO_CONTAINER (required)
#     Example:
#       infinito_nexus_arch

: "${INFINITO_APPS:?INFINITO_APPS is not set (e.g. INFINITO_APPS=web-app-nextcloud)}"
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set (e.g. infinito_nexus_arch)}"

echo "=== local cleanup: INFINITO_APPS=${INFINITO_APPS} container=${INFINITO_CONTAINER} ==="

: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR is not set; source scripts/meta/env/load.sh}"

docker exec -e INFINITO_APPS="${INFINITO_APPS}" "${INFINITO_CONTAINER}" \
	bash "${INFINITO_SRC_DIR}/scripts/container/purge/apps.sh"
