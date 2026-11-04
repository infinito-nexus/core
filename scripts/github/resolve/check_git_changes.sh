#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

if git diff --quiet -- "$@" &&
	[[ -z "$(git ls-files --others --exclude-standard -- "$@")" ]]; then
	echo "changed=false" >>"${GITHUB_OUTPUT}"
else
	echo "changed=true" >>"${GITHUB_OUTPUT}"
fi
