#!/usr/bin/env bash
#
# Dump runner disk + docker storage state with a leading label, used by
# images-build-ci to capture before/after of large multi-arch builds.
#
# Usage:
#   disk_pressure_report.sh LABEL    # LABEL = "START" / "END" / ...
set -euo pipefail

LABEL="${1:-snapshot}"

echo "=== Disk pressure: ${LABEL} ==="
echo "Runner: $(uname -a)"
echo
df -h
echo
docker version || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo
docker system df || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo
docker buildx version || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo
docker buildx du || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
