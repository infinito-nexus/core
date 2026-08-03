#!/usr/bin/env bash
set -euo pipefail

# Full swarm drill for ONE distro: bring the lab cluster up, matrix-deploy the
# app, seed/drain/assert, then always collect artefacts and tear the cluster
# down.
#
# The whole drill is one CI step, so $GITHUB_ENV writes never come back into the
# environment: the topology is sourced here, and the 05 -> 06 -> 07 handover goes
# through SWARM_DRILL_ENV, freshly created per distro so the previous distro's
# node names cannot leak into this one.
#
# Param:
#   APP_ID                              app id under test
#   SWARM_NAME                          cluster id
#   INFINITO_DISTRO                     distro under test (exported by distros.sh)
#   INFINITO_IMAGE_TAG                  tag the node image is looked up under
#   INFINITO_RESCUE_DIAGNOSTICS_BASE    host dir the rescue snapshots land under
#   INFINITO_SWARM_STEP_TIMEOUT_MINUTES deploy-step ceiling
#   variant                             optional matrix variant pin
#
# Exports:
#   MGR/WRK1/WRK2/NFS_SERVER/BACKUP_NODE and their *_IP peers, from the topology SPOT
#   SWARM_DRILL_ENV                     handover file for the routine steps

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
cd "${REPO_ROOT}"

set -a
# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "${SCRIPT_DIR}/../utils/topology/base.sh"
set +a

SWARM_DRILL_ENV="$(mktemp)"
export SWARM_DRILL_ENV

: "${APP_ID:?APP_ID is required (matrix.apps)}"
: "${INFINITO_DISTRO:?INFINITO_DISTRO is required (exported by scripts/tests/deploy/distros.sh)}"
: "${INFINITO_IMAGE_TAG:?INFINITO_IMAGE_TAG is required (source scripts/meta/env/load.sh before invoking this script)}"
: "${INFINITO_RESCUE_DIAGNOSTICS_BASE:?INFINITO_RESCUE_DIAGNOSTICS_BASE is required}"
: "${INFINITO_SWARM_STEP_TIMEOUT_MINUTES:?INFINITO_SWARM_STEP_TIMEOUT_MINUTES is required}"

collect_and_teardown() {
	rc=$?

	if [ "${rc}" -ne 0 ]; then
		rescue_dir="${INFINITO_RESCUE_DIAGNOSTICS_BASE}/${INFINITO_DISTRO}/${APP_ID}"
		INFINITO_RESCUE_DIAGNOSTICS_DIR="${rescue_dir}" \
			timeout 1500 python3 utils/diagnostics/container.py \
			"${APP_ID}" "post-deploy failure" || true
		INFINITO_RESCUE_DIAGNOSTICS_DIR="${rescue_dir}" \
			timeout 900 bash "${SCRIPT_DIR}/../utils/collect/diagnostics.sh" || true
		bash "${REPO_ROOT}/scripts/tests/deploy/utils/rescue_index.sh" "${rescue_dir}" || true
	fi

	timeout 900 bash "${SCRIPT_DIR}/../utils/collect/playwright_reports.sh" || true
	bash "${SCRIPT_DIR}/../utils/collect/topology_summary.sh" || true
	timeout 900 bash "${SCRIPT_DIR}/../utils/clean/teardown.sh" || true

	return "${rc}"
}
trap collect_and_teardown EXIT

INFINITO_IMAGE="$(bash "${REPO_ROOT}/scripts/meta/resolve/image/local.sh"):${INFINITO_IMAGE_TAG}"
if docker image inspect "${INFINITO_IMAGE}" >/dev/null 2>&1; then
	echo "==> node image: locally built ${INFINITO_IMAGE}"
else
	INFINITO_IMAGE="$(bash "${REPO_ROOT}/scripts/meta/resolve/image/ci.sh")"
	if [ -n "${INFINITO_IMAGE}" ]; then
		echo "==> node image: published ${INFINITO_IMAGE}"
	else
		echo "==> node image: unresolved, bootstrap will build it locally"
	fi
fi
export INFINITO_IMAGE

bash "${SCRIPT_DIR}/01_bootstrap.sh"

make setup

# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

matrix_cmd=(python3 -m utils.tests.swarm.matrix)
if [ "$(id -u)" -ne 0 ]; then
	matrix_cmd=(
		sudo -E env
		"PATH=$PATH"
		"HOME=$HOME"
		"SWARM_NAME=${SWARM_NAME:-}"
		"INFINITO_DISTRO=${INFINITO_DISTRO}"
		"INFINITO_IMAGE=${INFINITO_IMAGE:-}"
		"MGR=${MGR}"
		"MGR_IP=${MGR_IP}"
		"NFS_IP=${NFS_IP}"
		"variant=${variant:-}"
		"disable=${disable:-}"
		"${matrix_cmd[@]}"
	)
fi
timeout "$((INFINITO_SWARM_STEP_TIMEOUT_MINUTES * 60))" "${matrix_cmd[@]}"

bash "${SCRIPT_DIR}/05_seed_content.sh"
bash "${SCRIPT_DIR}/06_drain_worker.sh"
bash "${SCRIPT_DIR}/07_assert_state.sh"

echo "==> swarm drill complete: app=${APP_ID} distro=${INFINITO_DISTRO}"
