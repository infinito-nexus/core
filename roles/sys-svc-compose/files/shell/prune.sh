#!/bin/bash

set -euo pipefail

floor_mib="${PRUNE_FREE_FLOOR_MIB:?Missing PRUNE_FREE_FLOOR_MIB}"

# Exception: a probe that fails falls through to the prune, so unmeasured space counts as short.
if root="$(container info --format '{{.DockerRootDir}}' 2>/dev/null)" &&
  free_mib="$(df --output=avail -BM "${root}" 2>/dev/null | sed 1d | tr -dc '0-9')" &&
  [ -n "${free_mib}" ] && [ "${free_mib}" -ge "${floor_mib}" ]; then
  echo "Docker data root ${root} has ${free_mib} MiB free, at or above the ${floor_mib} MiB floor: prune skipped"
  exit 0
fi

echo "Docker disk usage before cleanup:"
container system df || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

container container prune -f || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
container image prune -af || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
container volume prune -f || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

container buildx prune -af || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
container builder prune -af || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

echo "Docker disk usage after cleanup:"
container system df || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
