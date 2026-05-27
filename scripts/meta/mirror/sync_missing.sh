#!/usr/bin/env bash
# Mirrors Docker Hub images to GHCR (only missing, best-effort).
# Required env vars: GHCR_NAMESPACE, GHCR_REPOSITORY, GHCR_PREFIX, REPO_ROOT
# Optional env vars: IMAGES_PER_HOUR
set -euo pipefail

echo ">>> Mirror namespace:  ${GHCR_NAMESPACE}"
echo ">>> Mirror repository: ${GHCR_REPOSITORY}"
echo ">>> Mirror prefix:     ${GHCR_PREFIX}"
echo ">>> Repo root:         ${REPO_ROOT}"
echo ">>> Mode:              only-missing"
echo ">>> Throttle:          ${IMAGES_PER_HOUR:-<disabled>} images/hour"

EXTRA_ARGS=()
if [[ -n "${IMAGES_PER_HOUR:-}" ]]; then
	EXTRA_ARGS+=(--images-per-hour "${IMAGES_PER_HOUR}")
fi

python -m cli.contributing.mirror.sync \
	--repo-root "${REPO_ROOT}" \
	--ghcr-namespace "${GHCR_NAMESPACE}" \
	--ghcr-repository "${GHCR_REPOSITORY}" \
	--ghcr-prefix "${GHCR_PREFIX}" \
	--only-missing \
	"${EXTRA_ARGS[@]}"

echo ">>> Mirror sync finished."
