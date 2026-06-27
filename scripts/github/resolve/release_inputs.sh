#!/usr/bin/env bash
#
# Resolve the release-version workflow's `vars` step output: validates
# the `tag` input, then queries the meta resolvers for owner / repo
# prefix / distro list and emits all four as GITHUB_OUTPUT lines.
#
# Usage:
#   release_inputs.sh VERSION_TAG
# Requires GITHUB_OUTPUT to be exported (provided by the runner).
set -euo pipefail

version_tag="$1"
[[ -n "$version_tag" ]] || {
	echo "ERROR: tag input is required"
	exit 1
}

owner="$(_helpers/scripts/meta/resolve/repository/owner.sh)"
repo_prefix="$(_helpers/scripts/meta/resolve/repository/name.sh)"
# shellcheck source=scripts/meta/env/load.sh
# shellcheck disable=SC1091
source "_helpers/scripts/meta/env/load.sh"
: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS}"

{
	echo "version_tag=${version_tag}"
	echo "distros=${INFINITO_DISTROS}"
	echo "repo_prefix=${repo_prefix}"
	echo "owner=${owner}"
} >>"$GITHUB_OUTPUT"
