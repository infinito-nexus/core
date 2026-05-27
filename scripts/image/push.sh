#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${MATRIX_DISTRO:?Missing MATRIX_DISTRO}"
export INFINITO_DISTRO="${MATRIX_DISTRO}"

# shellcheck source=scripts/meta/env/load.sh
source "${script_dir}/../meta/env/load.sh"

: "${BUILD_CONTEXT_DIR:?Missing BUILD_CONTEXT_DIR}"
: "${IMAGE_TAG:?Missing IMAGE_TAG}"
: "${GITHUB_REPOSITORY:?Missing GITHUB_REPOSITORY}"
: "${USE_NIX_TOKEN:?Missing USE_NIX_TOKEN}"
: "${INFINITO_PARENT_IMAGE:?Missing INFINITO_PARENT_IMAGE; source scripts/meta/env/load.sh}"
: "${INFINITO_SRC_DIR:?Missing INFINITO_SRC_DIR; source scripts/meta/env/load.sh}"
ghcr_owner="$(scripts/meta/resolve/repository/owner.sh)"
repo_name="$("${script_dir}/../meta/resolve/repository/name.sh")"

max_attempts="${MAX_ATTEMPTS:-7}"
retry_delay_seconds="${RETRY_DELAY_SECONDS:-20}"
attempt=1

nix_arg=()
if [[ "${USE_NIX_TOKEN}" == "true" ]]; then
	: "${NIX_GITHUB_TOKEN:?Missing NIX_GITHUB_TOKEN}"
	nix_arg=(--build-arg "NIX_CONFIG=access-tokens = github.com=${NIX_GITHUB_TOKEN}")
else
	echo "pull_request_target on fork detected: skipping NIX_CONFIG token build-arg."
fi

while true; do
	echo "=== Build & push attempt ${attempt}/${max_attempts} ==="

	if docker buildx build \
		--file "${BUILD_CONTEXT_DIR}/Dockerfile" \
		--push \
		--tag "ghcr.io/${ghcr_owner}/${repo_name}/${MATRIX_DISTRO}:${IMAGE_TAG}" \
		--label "org.opencontainers.image.source=https://github.com/${GITHUB_REPOSITORY}" \
		--build-arg "INFINITO_PARENT_IMAGE=${INFINITO_PARENT_IMAGE}" \
		--build-arg "INFINITO_SRC_DIR=${INFINITO_SRC_DIR}" \
		"${nix_arg[@]}" \
		--cache-from "type=gha,scope=${repo_name}-${MATRIX_DISTRO}" \
		--cache-to "type=gha,mode=max,scope=${repo_name}-${MATRIX_DISTRO}" \
		"${BUILD_CONTEXT_DIR}"; then
		echo "Build & push succeeded on attempt ${attempt}/${max_attempts}."
		break
	fi

	if [[ "${attempt}" -ge "${max_attempts}" ]]; then
		echo "Build & push failed after ${max_attempts} attempts."
		exit 1
	fi

	echo "Attempt ${attempt} failed. Retrying in ${retry_delay_seconds}s..."
	sleep "${retry_delay_seconds}"
	attempt=$((attempt + 1))
done
