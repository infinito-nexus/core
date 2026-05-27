#!/usr/bin/env bash
#
# Guard the version-release pipeline: only allow when the commit the
# version tag points at is contained in origin/main. Sets `allowed` on
# GITHUB_OUTPUT to true / false.
#
# Usage:
#   guard.sh
#   (reads VERSION_TAG from env; writes to GITHUB_OUTPUT)
set -euo pipefail

if [[ -z "${VERSION_TAG:-}" ]]; then
	echo "allowed=false" >>"$GITHUB_OUTPUT"
	echo "⛔ No version tag detected for this commit"
	exit 0
fi

tag="$VERSION_TAG"
tag_sha="$(git rev-list -n 1 "$tag")"
echo "Tag: ${tag} -> ${tag_sha}"

if git merge-base --is-ancestor "$tag_sha" "origin/main"; then
	echo "allowed=true" >>"$GITHUB_OUTPUT"
	echo "✅ Tag commit is on origin/main"
else
	echo "allowed=false" >>"$GITHUB_OUTPUT"
	echo "⛔ Tag commit is NOT on origin/main"
fi
