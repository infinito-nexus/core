#!/usr/bin/env bash
set -euo pipefail

docker exec "${INFINITO_CONTAINER}" bash -lc "
  echo \">>> Cleaning up lib \"
  rm -rv /var/lib/infinito/ || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
"
