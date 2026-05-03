#!/usr/bin/env bash
# Multiply Ansible task 'retries:' values by a factor across all role task files.
#
# Usage: multiply-timeouts.sh <multiplier> [repo-root]
#
# Safe to run on a CI workspace — actions/checkout provides a fresh copy each job,
# so in-place modifications are discarded before the next run.
#
# Only 'retries:' is scaled; 'delay:' is left unchanged so polling frequency stays
# the same and only the total wait window grows.
set -euo pipefail

MULTIPLIER="${1:-1}"
REPO_ROOT="${2:-$(pwd)}"

if [[ "${MULTIPLIER}" -le 1 ]]; then
	exit 0
fi

echo ">>> Multiplying Ansible retries by ${MULTIPLIER}x (self-hosted hardware)"

find "${REPO_ROOT}/roles" -path "*/tasks/*.yml" -name "*.yml" -print0 |
	xargs -0 -r perl -i -pe "s/^(\s+retries:\s+)(\d+)/\$1.(\$2*${MULTIPLIER})/e"

echo ">>> Done"
