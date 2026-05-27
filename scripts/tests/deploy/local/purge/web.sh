#!/usr/bin/env bash
set -euo pipefail

: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR is not set; source scripts/meta/env/load.sh}"

docker exec "${INFINITO_CONTAINER}" bash -lc "
  echo \">>> Cleaning up Nginx configuration files\"
  bash ${INFINITO_SRC_DIR}/scripts/container/purge/web.sh || true
"
