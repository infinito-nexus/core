#!/usr/bin/env bash
#
# Cleanup pass for the Docker / buildx state on a GitHub-hosted runner.
# Used by images-build-ci.yml as the always-on tail of the build job to
# free disk before the runner is reused (or recycled).
set -euo pipefail

echo "=== Cleanup ==="
docker buildx prune -af || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
docker builder prune -af || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
docker image prune -af || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
docker container prune -f || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo
echo "=== Disk pressure: AFTER CLEANUP ==="
df -h
echo
docker system df || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
docker buildx du || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
