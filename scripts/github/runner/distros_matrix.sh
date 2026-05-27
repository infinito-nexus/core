#!/usr/bin/env bash
#
# Emit a JSON array matrix from a space-separated distro list. Used by
# images-build-ci and test-dns workflows to feed the matrix strategy.
#
# Usage:
#   distros_matrix.sh "arch debian ubuntu"
#   echo "matrix=$(distros_matrix.sh "${INPUT}")" >> "$GITHUB_OUTPUT"
set -euo pipefail

distros="${1:-}"
printf '%s' "${distros}" | jq -Rc 'split(" ") | map(select(length>0))'
