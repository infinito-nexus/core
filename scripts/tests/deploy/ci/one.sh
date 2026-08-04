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
: "${INFINITO_DEPLOY_MODE:?INFINITO_DEPLOY_MODE is required (declared by the deploy workflow)}"

# shellcheck source=scripts/tests/deploy/utils/filesystem/pick.sh
. "${REPO_ROOT}/scripts/tests/deploy/utils/filesystem/pick.sh"
filesystem_pick "${INFINITO_DEPLOY_MODE}/${apps}/${INFINITO_DISTRO}" runner
if [ -n "${INFINITO_DOCKER_FILESYSTEM:-}" ]; then
	sudo -E "${REPO_ROOT}/scripts/tests/deploy/utils/filesystem/docker_dataroot.sh" \
		"${INFINITO_DOCKER_FILESYSTEM}" "${INFINITO_DOCKER_FILESYSTEM_REQUIRED}" 30G \
		"${INFINITO_DEPLOY_MODE}-runner"
fi

INFINITO_IMAGE="$(bash "${REPO_ROOT}/scripts/meta/resolve/image/ci.sh")"
export INFINITO_IMAGE

if [[ -f "${SCRIPT_DIR}/custom/${apps}.sh" ]]; then
	exec bash "${SCRIPT_DIR}/custom/${apps}.sh"
fi

exec "${SCRIPT_DIR}/dedicated.sh" --apps "${apps}"
