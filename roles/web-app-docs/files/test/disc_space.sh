#!/usr/bin/env bash
# shellcheck shell=bash
#
# Args:
#   $1  the extracted production block, rewritten in place
#
# Env (test.env):
#   DOCS_TEST_DISC_SPACE_PERCENT  the stack host's SIZE_PERCENT_CLEANUP_DISC_SPACE

set -euo pipefail

BLOCK="${1:?}"
PERCENT="${DOCS_TEST_DISC_SPACE_PERCENT:?}"
VARS='--vars "{'
ENTRY='\\"SIZE_PERCENT_CLEANUP_DISC_SPACE\\": '"${PERCENT}"', '

if ! [[ "${PERCENT}" =~ ^[0-9]+$ ]]; then
	echo "DOCS_TEST_DISC_SPACE_PERCENT='${PERCENT}' is no whole percentage" >&2
	exit 1
fi

if ! grep -qF -- "${VARS}" "${BLOCK}"; then
	echo "the block hands provision no ${VARS}...}', so the disc-space limit has nothing to attach to" >&2
	exit 1
fi

echo "=== Judging the target's disc by the stack host's ${PERCENT}% limit ==="
sed -i "s#${VARS}#${VARS}${ENTRY}#" "${BLOCK}"
