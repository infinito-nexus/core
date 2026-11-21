#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

codex --version
if [[ "${GATEWAY_ENABLED}" == "true" ]]; then
  "${TEST_PYTHON}" /usr/local/lib/infinito/tests/dsk-gnt-codex/validate_codex.py --program "${CODEX_MODE_PROGRAM}" --home "${CODEX_USER_HOME}" --timeout "${TEST_TIMEOUT}"
fi
