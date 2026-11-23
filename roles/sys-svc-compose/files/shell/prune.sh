#!/bin/bash

set -euo pipefail

floor_mib="${PRUNE_FREE_FLOOR_MIB:?Missing PRUNE_FREE_FLOOR_MIB}"
repeat_below_percent="${PRUNE_REPEAT_BELOW_PERCENT:?Missing PRUNE_REPEAT_BELOW_PERCENT}"
last_free_mib="${PRUNE_LAST_FREE_MIB?Missing PRUNE_LAST_FREE_MIB}"

free_mib() {
  df --output=avail -BM "${root}" 2>/dev/null | sed 1d | tr -dc '0-9'
}

# Exception: a probe that fails falls through to the prune, so unmeasured space counts as short.
if root="$(container info --format '{{.DockerRootDir}}' 2>/dev/null)" &&
  free="$(free_mib)" && [ -n "${free}" ]; then
  if [ "${free}" -ge "${floor_mib}" ]; then
    echo "Docker data root ${root} has ${free} MiB free, at or above the ${floor_mib} MiB floor: prune skipped"
    exit 0
  fi
  if [ -n "${last_free_mib}" ] &&
    [ $((last_free_mib * 100)) -ge $((floor_mib * repeat_below_percent)) ] &&
    [ $((free * 100)) -gt $((last_free_mib * repeat_below_percent)) ]; then
    echo "Docker data root ${root} has ${free} MiB free, above ${repeat_below_percent}% of the ${last_free_mib} MiB the last prune of this run kept: prune skipped"
    exit 0
  fi
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

if [ -n "${root}" ] && kept="$(free_mib)" && [ -n "${kept}" ] && [ "${kept}" -lt "${floor_mib}" ]; then
  echo "Docker data root ${root} kept ${kept} MiB free after the prune, below the ${floor_mib} MiB floor"
fi
