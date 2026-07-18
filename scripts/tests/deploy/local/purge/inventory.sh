#!/usr/bin/env bash
set -euo pipefail

docker exec "${INFINITO_CONTAINER}" bash -lc "
  echo \">>> Deleting inventory \"
  rm -rv ${INFINITO_INVENTORY_DIR} || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
"
