#!/usr/bin/env bash
set -euo pipefail

# Deploy `apps` on the distro the loop is currently on: the per-app override
# when the app ships one, otherwise the shared dedicated.sh path.
#
# Param:
#   apps                app id under test
#   INFINITO_DISTRO     distro under test (exported by distros.sh)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

: "${apps:?apps is required (e.g. apps=web-app-keycloak)}"
: "${INFINITO_DISTRO:?INFINITO_DISTRO is required (exported by scripts/tests/deploy/distros.sh)}"

INFINITO_IMAGE="$(bash "${REPO_ROOT}/scripts/meta/resolve/image/ci.sh")"
export INFINITO_IMAGE

if [[ -f "${SCRIPT_DIR}/custom/${apps}.sh" ]]; then
	exec bash "${SCRIPT_DIR}/custom/${apps}.sh"
fi

exec "${SCRIPT_DIR}/dedicated.sh" --apps "${apps}"
