#!/usr/bin/env bash
# Argv: <distro> [<distro> ...]  (falls back to INFINITO_DISTROS)
#
# Env:
#   IMAGE_TAG            the plain tag to create (required)
#   IMAGE_ARCHITECTURES  space-separated architectures to merge (required)
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

: "${IMAGE_TAG:?Missing IMAGE_TAG}"
: "${IMAGE_ARCHITECTURES:?Missing IMAGE_ARCHITECTURES}"

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
	target="ghcr.io/${ghcr_owner}/${repo_name}/${distro}:${IMAGE_TAG}"
	sources=()
	for arch in "${architectures[@]}"; do
		sources+=("${target}-${arch}")
	done

	echo "🏗️  ${target} <- ${sources[*]}"
	if docker buildx imagetools create --tag "${target}" "${sources[@]}"; then
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

echo "🎉 ${#distros[@]} multi-architecture image(s) published"
