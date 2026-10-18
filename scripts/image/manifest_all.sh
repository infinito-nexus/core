#!/usr/bin/env bash
# Argv: <distro> [<distro> ...]  (falls back to INFINITO_DISTROS)
#
# Env:
#   IMAGE_TAG            the one tag every distro gets (required)
#   IMAGE_ARCHITECTURES  space-separated architectures the tag must cover (required)
#   IMAGE_DIGEST_DIR     directory holding one <distro>.<arch> digest file per build (required)
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

: "${IMAGE_TAG:?Missing IMAGE_TAG}"
: "${IMAGE_ARCHITECTURES:?Missing IMAGE_ARCHITECTURES}"
: "${IMAGE_DIGEST_DIR:?Missing IMAGE_DIGEST_DIR}"

distros=("$@")
if ((${#distros[@]} == 0)); then
	: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS and no distro arguments}"
	read -r -a distros <<<"${INFINITO_DISTROS}"
fi

read -r -a architectures <<<"${IMAGE_ARCHITECTURES}"

ghcr_owner="$("${repo_root}/scripts/meta/resolve/repository/owner.sh")"
repo_name="$("${repo_root}/scripts/meta/resolve/repository/name.sh")"

failed=()
for distro in "${distros[@]}"; do
	image="ghcr.io/${ghcr_owner}/${repo_name}/${distro}"
	sources=()
	for arch in "${architectures[@]}"; do
		digest_file="${IMAGE_DIGEST_DIR}/${distro}.${arch}"
		if [[ ! -s "${digest_file}" ]]; then
			echo "❌ ${distro}: no linux/${arch} digest at ${digest_file}"
			sources=()
			break
		fi
		sources+=("${image}@$(<"${digest_file}")")
	done

	if ((${#sources[@]} == 0)); then
		failed+=("${distro}")
		continue
	fi

	echo "🏗️  ${image}:${IMAGE_TAG} <- ${sources[*]}"
	if docker buildx imagetools create --tag "${image}:${IMAGE_TAG}" "${sources[@]}"; then
		echo "✅ ${distro}"
	else
		echo "❌ ${distro}"
		failed+=("${distro}")
	fi
done

if ((${#failed[@]} > 0)); then
	echo "❌ Failed manifests: ${failed[*]}"
	exit 1
fi

echo "🎉 ${#distros[@]} image(s) tagged ${IMAGE_TAG} for ${architectures[*]}"
