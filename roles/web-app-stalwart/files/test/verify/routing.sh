#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

: "${PYTHON_BIN:?missing PYTHON_BIN}"

"${PYTHON_BIN}" "${SCRIPT_DIR}/../probe/stalwart.py" routing
echo "[routing] every declared alias, catch-all and forward reached its destinations"
