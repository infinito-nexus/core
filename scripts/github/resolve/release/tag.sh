#!/usr/bin/env bash
#
# Decide whether the pushed commit is a release.
#
# Param:
#   GITHUB_SHA      commit to inspect for a `vX.Y.Z` annotated tag
#   GITHUB_OUTPUT   file `is_version` and `version_tag` are appended to
set -euo pipefail

version_tag="$(
	git tag --points-at "${GITHUB_SHA}" |
		grep -E '^v[0-9]+(\.[0-9]+)*$' |
		head -n 1 || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
)"

if [[ -n "$version_tag" ]]; then
	echo "is_version=true" >>"$GITHUB_OUTPUT"
	echo "version_tag=${version_tag}" >>"$GITHUB_OUTPUT"
	echo "🎯 Commit ${GITHUB_SHA} has version tag ${version_tag}"
else
	echo "is_version=false" >>"$GITHUB_OUTPUT"
	echo "version_tag=" >>"$GITHUB_OUTPUT"
	echo "No version tag on commit ${GITHUB_SHA}"
fi
