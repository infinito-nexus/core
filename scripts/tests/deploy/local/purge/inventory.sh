#!/usr/bin/env bash
set -euo pipefail

docker exec "${INFINITO_CONTAINER}" bash -lc "
  echo \">>> Deleting inventory \"
  rm -rv ${INFINITO_INVENTORY_DIR} || true
"
