#!/usr/bin/env bash
set -euo pipefail

# Full swarm drill for ONE distro: bring the lab cluster up, matrix-deploy the
# app, seed/drain/assert, then always collect artefacts and tear the cluster
# down.
#
# Param:
#   APP_ID                              app id under test
#   SWARM_NAME                          cluster id
#   INFINITO_DISTRO                     distro under test (exported by distros.sh)
#   INFINITO_RESCUE_DIAGNOSTICS_BASE    host dir the rescue snapshots land under
#   INFINITO_SWARM_STEP_TIMEOUT_MINUTES deploy-step ceiling
#   variant                             optional matrix variant pin

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
cd "${REPO_ROOT}"

: "${APP_ID:?APP_ID is required (matrix.apps)}"
: "${INFINITO_DISTRO:?INFINITO_DISTRO is required (exported by scripts/tests/deploy/distros.sh)}"
: "${INFINITO_RESCUE_DIAGNOSTICS_BASE:?INFINITO_RESCUE_DIAGNOSTICS_BASE is required}"
: "${INFINITO_SWARM_STEP_TIMEOUT_MINUTES:?INFINITO_SWARM_STEP_TIMEOUT_MINUTES is required}"

collect_and_teardown() {
	rc=$?

	if [ "${rc}" -ne 0 ]; then
		INFINITO_RESCUE_DIAGNOSTICS_DIR="${INFINITO_RESCUE_DIAGNOSTICS_BASE}/${INFINITO_DISTRO}/${APP_ID}" \
			timeout 1500 python3 utils/diagnostics/container.py \
			"${APP_ID}" "post-deploy failure" || true
		timeout 900 bash "${SCRIPT_DIR}/../utils/collect/diagnostics.sh" || true
	fi

	timeout 900 bash "${SCRIPT_DIR}/../utils/collect/playwright_reports.sh" || true
	bash "${SCRIPT_DIR}/../utils/collect/topology_summary.sh" || true
	timeout 900 bash "${SCRIPT_DIR}/../utils/clean/teardown.sh" || true

	return "${rc}"
}
trap collect_and_teardown EXIT

INFINITO_IMAGE="$(bash "${REPO_ROOT}/scripts/meta/resolve/image/ci.sh")"
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
		"variant=${variant:-}"
		"disable=${disable:-}"
		"${matrix_cmd[@]}"
	)
fi
timeout "$((INFINITO_SWARM_STEP_TIMEOUT_MINUTES * 60))" "${matrix_cmd[@]}"

bash "${SCRIPT_DIR}/05_seed_content.sh"
bash "${SCRIPT_DIR}/06_drain_worker.sh"
bash "${SCRIPT_DIR}/07_assert_state.sh"
