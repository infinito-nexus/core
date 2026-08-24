#!/usr/bin/env bash
#
# Resolve the chunk's deploy matrix and write it to GITHUB_OUTPUT.
# Inputs via env (forwarded to scripts/meta/resolve/apps.sh):
#   INFINITO_CI_CHUNK — chunk index to emit
#   INFINITO_CI_SWEEP — sweep number
#   INFINITO_WHITELIST / INFINITO_PRIORITY / INFINITO_MODES / INFINITO_TOR
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

matrix="$(./scripts/meta/resolve/apps.sh)"
[[ -n "$matrix" ]] || matrix='[]'

echo "apps=$matrix" >>"$GITHUB_OUTPUT"
echo "apps=$matrix"
