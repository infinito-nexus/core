#!/usr/bin/env bash
# Waits until every role-declared image has been mirrored to GHCR.
# Required env vars: GHCR_NAMESPACE, GHCR_REPOSITORY, GHCR_PREFIX, REPO_ROOT,
#                    IMAGE_WAIT_SLEEP_SECONDS, IMAGE_WAIT_ATTEMPTS
set -euo pipefail

: "${GHCR_NAMESPACE:?Missing GHCR_NAMESPACE}"
: "${GHCR_REPOSITORY:?Missing GHCR_REPOSITORY}"
: "${GHCR_PREFIX:?Missing GHCR_PREFIX}"
: "${REPO_ROOT:?Missing REPO_ROOT}"
: "${IMAGE_WAIT_SLEEP_SECONDS:?Missing IMAGE_WAIT_SLEEP_SECONDS}"
: "${IMAGE_WAIT_ATTEMPTS:?Missing IMAGE_WAIT_ATTEMPTS}"

python -m cli.contributing.mirror.wait \
	--repo-root "${REPO_ROOT}" \
	--ghcr-namespace "${GHCR_NAMESPACE}" \
	--ghcr-repository "${GHCR_REPOSITORY}" \
	--ghcr-prefix "${GHCR_PREFIX}" \
	--attempts "${IMAGE_WAIT_ATTEMPTS}" \
	--sleep-seconds "${IMAGE_WAIT_SLEEP_SECONDS}"
