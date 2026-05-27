#!/usr/bin/env bash
#
# Cleanup pass for the Docker / buildx state on a GitHub-hosted runner.
# Used by images-build-ci.yml as the always-on tail of the build job to
# free disk before the runner is reused (or recycled).
set -euo pipefail

echo "=== Cleanup ==="
docker buildx prune -af || true
docker builder prune -af || true
docker image prune -af || true
docker container prune -f || true
echo
echo "=== Disk pressure: AFTER CLEANUP ==="
df -h
echo
docker system df || true
docker buildx du || true
