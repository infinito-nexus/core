#!/usr/bin/env bash
set -euo pipefail

# Retag already built CI images (ci-<sha>) to <version> and, for the highest
# version only, to latest as well (no rebuild).

OWNER="${OWNER:-${GITHUB_REPOSITORY_OWNER:-}}"
OWNER="$(OWNER="${OWNER}" GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" scripts/meta/resolve/repository/owner.sh)"
[[ -n "${OWNER}" ]] || {
	echo "ERROR: OWNER not set"
	exit 2
}

REGISTRY="${REGISTRY:-ghcr.io}"
: "${REPO_PREFIX:?Missing REPO_PREFIX}"
: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS}"
DEFAULT_DISTRO="${DEFAULT_DISTRO:-debian}"
PUBLISH_LATEST="${PUBLISH_LATEST:-true}"
REPO_PREFIX="${REPO_PREFIX,,}"

# VERSION_TAG must be like "v1.2.3"
VERSION_TAG="${VERSION_TAG:-${GITHUB_REF_NAME:-}}"
[[ -n "${VERSION_TAG}" ]] || {
	echo "ERROR: VERSION_TAG not set"
	exit 2
}

# CI_TAG should be "ci-<sha>"
CI_TAG="${CI_TAG:-ci-${GITHUB_SHA:-}}"
[[ -n "${CI_TAG}" ]] || {
	echo "ERROR: CI_TAG not set"
	exit 2
}

echo "Retagging CI images:"
echo "  CI_TAG      = ${CI_TAG}"
echo "  VERSION_TAG = ${VERSION_TAG}"
echo "  INFINITO_DISTROS     = ${INFINITO_DISTROS}"
echo "  PUBLISH_LATEST = ${PUBLISH_LATEST}"

retag_set() {
	local src="$1"
	local dst_ver="$2"
	local dst_latest="${3:-}"
	local args=()

	echo "    source: ${src}"
	echo "    target: ${dst_ver}"
	args+=(-t "${dst_ver}")

	if [[ -n "${dst_latest}" ]]; then
		echo "    target: ${dst_latest}"
		args+=(-t "${dst_latest}")
	fi

	docker buildx imagetools create \
		"${args[@]}" \
		"${src}"
}

for distro in ${INFINITO_DISTROS}; do
	echo
	echo "==> ${distro}"

	# NORMAL
	src="${REGISTRY}/${OWNER}/${REPO_PREFIX}/${distro}:${CI_TAG}"
	dst_ver="${REGISTRY}/${OWNER}/${REPO_PREFIX}/${distro}:${VERSION_TAG}"
	dst_latest=""
	if [[ "${PUBLISH_LATEST}" == "true" ]]; then
		dst_latest="${REGISTRY}/${OWNER}/${REPO_PREFIX}/${distro}:latest"
	fi
	retag_set "${src}" "${dst_ver}" "${dst_latest}"

	# Alias for default distro
	if [[ "${distro}" == "${DEFAULT_DISTRO}" ]]; then
		alias_ver="${REGISTRY}/${OWNER}/${REPO_PREFIX}:${VERSION_TAG}"
		alias_latest=""
		if [[ "${PUBLISH_LATEST}" == "true" ]]; then
			alias_latest="${REGISTRY}/${OWNER}/${REPO_PREFIX}:latest"
		fi
		retag_set "${src}" "${alias_ver}" "${alias_latest}"
	fi
done

echo
echo "Done retagging CI images."
