#!/usr/bin/env bash
#
# Decide which distros the latest-push CI run should cover. If the
# pushed commit carries a `vX.Y.Z` annotated tag, run every declared
# distro; otherwise pick one at random. Emits both `is_version` and
# `distros` to GITHUB_OUTPUT. The distro set comes from INFINITO_DISTROS,
# which the env layer generates from the meta/distros.yml SPOT.
#
# Usage:
#   pick_distro.sh
#   (reads GITHUB_SHA from env; writes to GITHUB_OUTPUT)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
source "${REPO_ROOT}/scripts/meta/env/load.sh"
: "${INFINITO_DISTROS:?INFINITO_DISTROS must be resolved by scripts/meta/env/load.sh}"
read -r -a ALL_DISTROS <<<"${INFINITO_DISTROS}"

version_tag="$(
	git tag --points-at "${GITHUB_SHA}" |
		grep -E '^v[0-9]+(\.[0-9]+)*$' |
		head -n 1 || true
)"

if [[ -n "$version_tag" ]]; then
	echo "is_version=true" >>"$GITHUB_OUTPUT"
	echo "version_tag=${version_tag}" >>"$GITHUB_OUTPUT"
	distros="${ALL_DISTROS[*]}"
	echo "🎯 Commit ${GITHUB_SHA} has version tag ${version_tag} → running ALL distros"
else
	echo "is_version=false" >>"$GITHUB_OUTPUT"
	echo "version_tag=" >>"$GITHUB_OUTPUT"
	one="$(printf '%s\n' "${ALL_DISTROS[@]}" | shuf -n 1)"
	distros="$one"
	echo "🎲 No version tag on commit → picked distro: ${one}"
fi

echo "distros=${distros}" >>"$GITHUB_OUTPUT"
echo "=== Selected distros: ${distros} ==="
echo "=== is_version: $(grep -E '^is_version=' "$GITHUB_OUTPUT" | tail -n 1) ==="
echo "=== version_tag: $(grep -E '^version_tag=' "$GITHUB_OUTPUT" | tail -n 1) ==="
