#!/usr/bin/env bash
#
# Resolve the app list and write it to GITHUB_OUTPUT.
# Inputs via env (forwarded to scripts/meta/resolve/apps.sh):
#   INFINITO_WHITELIST — optional space-separated allowlist
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/python.sh
source "${REPO_ROOT}/scripts/meta/env/python.sh"

apps="$(./scripts/meta/resolve/apps.sh)"
[[ -n "$apps" ]] || apps='[]'

matrix="$(printf '%s' "$apps" | "${PYTHON}" -m utils.github.variant_bundles)"
[[ -n "$matrix" ]] || matrix='[]'

echo "apps=$matrix" >>"$GITHUB_OUTPUT"
echo "apps=$matrix"
