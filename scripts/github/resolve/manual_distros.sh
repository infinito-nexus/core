#!/usr/bin/env bash
#
# Resolve the distro list a manual CI run sweeps and write it to GITHUB_OUTPUT.
# A caller-supplied list is used verbatim; an empty one picks a single distro
# at random, the same way scripts/github/resolve/pick_distro.sh does for
# untagged pushes. The distro set comes from INFINITO_DISTROS, which the env
# layer generates from the meta/distros.yml SPOT.
#
# Param:
#   INPUT_DISTROS   caller-supplied space-separated distro list; empty randomises
#   GITHUB_OUTPUT   file the resolved `distros=<value>` is appended to
set -euo pipefail

: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
source "${REPO_ROOT}/scripts/meta/env/load.sh"
: "${INFINITO_DISTROS:?INFINITO_DISTROS must be resolved by scripts/meta/env/load.sh}"

input="${INPUT_DISTROS:-}"

if [[ -n "${input//[[:space:]]/}" ]]; then
	distros="${input}"
	echo "🎯 Caller-supplied distros: ${distros}"
else
	read -r -a all_distros <<<"${INFINITO_DISTROS}"
	distros="$(printf '%s\n' "${all_distros[@]}" | shuf -n 1)"
	echo "🎲 No distros requested → picked at random: ${distros}"
fi

printf 'distros=%s\n' "${distros}" >>"${GITHUB_OUTPUT}"
