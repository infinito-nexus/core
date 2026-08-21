#!/usr/bin/env bash
set -euo pipefail

# Replay one role's README "Production" block on the distro the loop is
# currently on, in the mode the role dictates, then release the compose server.
#
# Param:
#   GUIDE_ROLE                          role under test
#   GUIDE_MODE                          host | compose
#   INFINITO_DISTRO                     distro under test (exported by distros.sh)
#   INFINITO_IMAGE_TAG                  tag the CI environment images were pushed under
#   INFINITO_PARENT_IMAGE_OWNER         owner of the pkgmgr base images
#   INFINITO_PARENT_IMAGE_TAG           tag of the pkgmgr base images
#   INFINITO_RESCUE_DIAGNOSTICS_BASE    host dir the rescue snapshots land under

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

: "${GUIDE_ROLE:?GUIDE_ROLE is required (cli.meta.ci.guide_select)}"
: "${GUIDE_MODE:?GUIDE_MODE is required (cli.meta.ci.guide_select)}"
: "${INFINITO_DISTRO:?INFINITO_DISTRO is required (exported by scripts/tests/deploy/distros.sh)}"
: "${INFINITO_PARENT_IMAGE_OWNER:?INFINITO_PARENT_IMAGE_OWNER is required (default.env)}"
: "${INFINITO_PARENT_IMAGE_TAG:?INFINITO_PARENT_IMAGE_TAG is required (default.env)}"
: "${INFINITO_RESCUE_DIAGNOSTICS_BASE:?INFINITO_RESCUE_DIAGNOSTICS_BASE is required (default.env)}"

GUIDE_RUNTIME_IMAGE="$(python3 -m cli.meta.ci.image_ref --kind pkgmgr \
	--distro "${INFINITO_DISTRO}" \
	--owner "${INFINITO_PARENT_IMAGE_OWNER}" \
	--tag "${INFINITO_PARENT_IMAGE_TAG}")"
export GUIDE_RUNTIME_IMAGE

echo "=== Guide: role=${GUIDE_ROLE} mode=${GUIDE_MODE} distro=${INFINITO_DISTRO} ==="

if [ "${GUIDE_MODE}" = "host" ]; then
	exec bash "${SCRIPT_DIR}/host_deploy.sh"
fi

INFINITO_IMAGE="$(bash "${REPO_ROOT}/scripts/meta/resolve/image/ci.sh")"
export INFINITO_IMAGE

release() {
	rc=$?

	if [ "${rc}" -ne 0 ]; then
		guide_rescue_dir="${INFINITO_RESCUE_DIAGNOSTICS_BASE}/${INFINITO_DISTRO}/${GUIDE_ROLE}"
		INFINITO_RESCUE_DIAGNOSTICS_DIR="${guide_rescue_dir}" \
			timeout 1500 python3 utils/diagnostics/container.py \
			"${GUIDE_ROLE}" "guide compose post-deploy failure" || true # nocheck: shell-or-true -- best-effort diagnostics + teardown in the EXIT trap
		bash scripts/tests/deploy/utils/rescue_index.sh "${guide_rescue_dir}"
	fi

	make compose-down || true # nocheck: shell-or-true -- best-effort diagnostics + teardown in the EXIT trap

	return "${rc}"
}
trap release EXIT

make compose-up
bash "${SCRIPT_DIR}/compose_deploy.sh"
