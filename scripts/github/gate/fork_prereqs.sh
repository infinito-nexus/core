#!/usr/bin/env bash
#
# Inputs via env:
#   RESULT  the wait-fork-prereq-run job result (needs.<job>.result).

set -euo pipefail

: "${RESULT:?}"

if [[ "${RESULT}" != "success" && "${RESULT}" != "skipped" ]]; then
	echo "Fork prerequisites are not ready. wait-fork-prereq-run=${RESULT}" >&2
	exit 1
fi
echo "Fork prerequisites are ready."
