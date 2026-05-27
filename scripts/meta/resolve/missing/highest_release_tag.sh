#!/usr/bin/env bash
set -euo pipefail

: "${OWNER:?Missing OWNER}"
: "${REGISTRY:?Missing REGISTRY}"
: "${REPO_PREFIX:?Missing REPO_PREFIX}"
: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

OWNER="$("${script_dir}/../repository/owner.sh")"
REPO_PREFIX="${REPO_PREFIX,,}"

mapfile -t tags < <("${script_dir}/../version_tags.sh")

if [[ ${#tags[@]} -eq 0 ]]; then
	exit 0
fi

for ((i = ${#tags[@]} - 1; i >= 0; i--)); do
	tag="${tags[$i]}"
	tag_missing="false"

	for distro in ${INFINITO_DISTROS}; do
		img="${REGISTRY}/${OWNER}/${REPO_PREFIX}/${distro}:${tag}"
		echo "Check: ${img}" >&2
		if docker manifest inspect "${img}" >/dev/null 2>&1; then
			echo "  OK" >&2
		else
			echo "  MISSING" >&2
			tag_missing="true"
		fi
	done

	alias_img="${REGISTRY}/${OWNER}/${REPO_PREFIX}:${tag}"
	echo "Check: ${alias_img}" >&2
	if docker manifest inspect "${alias_img}" >/dev/null 2>&1; then
		echo "  OK" >&2
	else
		echo "  MISSING" >&2
		tag_missing="true"
	fi

	if [[ "${tag_missing}" == "true" ]]; then
		printf '%s\n' "${tag}"
		exit 0
	fi
done
