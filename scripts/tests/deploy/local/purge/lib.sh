#!/usr/bin/env bash
set -euo pipefail

docker exec "${INFINITO_CONTAINER}" bash -lc "
  echo \">>> Cleaning up lib \"
  rm -rv ${INFINITO_DIR_VAR_LIB:?}/ || true
"
