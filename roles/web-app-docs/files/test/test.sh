#!/usr/bin/env bash
# shellcheck shell=bash
#
# Env (templates/test.env.j2):
#   DOCS_TEST_BASE_URL    documentation service on this host
#   DOCS_TEST_ROLE        role whose page carries the instructions
#   DOCS_TEST_STACK_HOST  true on the stack host, the one host of a deploy that
#                         replays
#   DOCS_TEST_TIMEOUT     seconds to wait for the on-demand build

set -euo pipefail

: "${DOCS_TEST_BASE_URL:?}"
: "${DOCS_TEST_ROLE:?}"
: "${DOCS_TEST_STACK_HOST:?}"
: "${DOCS_TEST_TIMEOUT:?}"

if [ "${DOCS_TEST_STACK_HOST}" != "true" ]; then
	echo "SKIP: the stack host replays the instructions onto the shared target;"
	echo "      this host is not it."
	exit 0
fi

STAGE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLOCK="${STAGE}/block.sh"

echo "=== Reading the published instructions for ${DOCS_TEST_ROLE} ==="
python3 "${STAGE}/extract.py" "${DOCS_TEST_BASE_URL}" "${DOCS_TEST_ROLE}" \
	--timeout "${DOCS_TEST_TIMEOUT}" >"${BLOCK}"

if [ ! -s "${BLOCK}" ]; then
	echo "ERROR: the page for ${DOCS_TEST_ROLE} shows an empty Production block." >&2
	exit 1
fi

bash "${STAGE}/mirror.sh" "${BLOCK}"
python3 "${STAGE}/hlth_runtime.py" "${BLOCK}"
bash "${STAGE}/disc_space.sh" "${BLOCK}"

echo "=== Checking they parse as bash ==="
bash -n "${BLOCK}"

bash "${STAGE}/replay.sh" "${BLOCK}"
