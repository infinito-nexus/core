#!/usr/bin/env bash
set -euo pipefail

: "${TEST_UNIFIED_ENABLED:?}"
if [[ "${TEST_UNIFIED_ENABLED}" != 1 ]]; then
    echo "SKIP: unified Claude configuration is not enabled for this host"
    exit 0
fi

: "${CLAUDE_MODE_PROGRAM:?}"
: "${CLAUDE_BINARY:?}"
: "${CODE_BINARY:?}"
: "${TEST_CONFIG_PATH:?}"
: "${TEST_PYTHON:?}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${TEST_PYTHON}" "${here}/unified.py"
