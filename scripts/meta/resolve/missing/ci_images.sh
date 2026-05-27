#!/usr/bin/env bash
set -euo pipefail

: "${OWNER:?Missing OWNER}"
: "${CI_TAG:?Missing CI_TAG}"
: "${REGISTRY:?Missing REGISTRY}"
: "${REPO_PREFIX:?Missing REPO_PREFIX}"
: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

OWNER="$("${script_dir}/../repository/owner.sh")"
REPO_PREFIX="${REPO_PREFIX,,}"

missing="false"

for distro in ${INFINITO_DISTROS}; do
	img="${REGISTRY}/${OWNER}/${REPO_PREFIX}/${distro}:${CI_TAG}"
	echo "Check: ${img}" >&2
	if docker manifest inspect "${img}" >/dev/null 2>&1; then
		echo "  OK" >&2
	else
		echo "  MISSING" >&2
		missing="true"
	fi
done

printf '%s\n' "${missing}"
