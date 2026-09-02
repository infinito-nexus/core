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
#   disable                             optional provider keys to render disabled,
#                                       minus SWARM_REQUIRED_SERVICES
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
: "${INFINITO_SWARM_TEARDOWN_RESERVE_SECONDS:?INFINITO_SWARM_TEARDOWN_RESERVE_SECONDS is required}"

SWARM_REQUIRED_SERVICES="node nfs-server container_backup nfs_backup"
if [ -n "${disable:-}" ]; then
	_keep="" _drop=""
	IFS=', ' read -r -a _keys <<<"${disable}"
	for _key in "${_keys[@]}"; do
		[ -n "${_key}" ] || continue
		case " ${SWARM_REQUIRED_SERVICES} " in
		*" ${_key} "*) _drop="${_drop}${_drop:+,}${_key}" ;;
		*) _keep="${_keep}${_keep:+,}${_key}" ;;
		esac
	done
	if [ -n "${_drop}" ]; then
		echo "==> disable: keeping '${_drop}' enabled -- the swarm drill needs them"
	fi
	disable="${_keep}"
	export disable
	unset _keep _drop _key _keys
fi

teardown_floor_seconds=120
collect_floor_seconds=120
index_floor_seconds=30

# Param: $1 nominal seconds for this step
# Param: $2 seconds to leave behind for the steps that follow it
# Param: $3.. the command to run
run_within_deadline() {
	_nominal=${1}
	_leave=${2}
	shift 2
	if [ -n "${INFINITO_CI_DISTRO_DEADLINE_EPOCH:-}" ]; then                       # nocheck: distros.sh computes this epoch from the sweep budget at run time; a static default would be a stale timestamp
		_usable=$((INFINITO_CI_DISTRO_DEADLINE_EPOCH - $(date +%s) - _leave)) # nocheck: run-time state, not a configurable default
		if [ "${_usable}" -lt 5 ]; then
			echo "==> teardown: no budget left before the sweep deadline, skipping ${1}"
			return 0
		fi
		if [ "${_usable}" -lt "${_nominal}" ]; then
			echo "==> teardown: capping ${1} at ${_usable}s of ${_nominal}s to hold the sweep deadline"
			_nominal=${_usable}
		fi
	fi
	_rc=0
	timeout "${_nominal}" "$@" || _rc=$?
	if [ "${_rc}" -eq 124 ]; then
		echo "==> teardown: ${1} was cut off at ${_nominal}s, so whatever it collects is incomplete"
	fi
	return "${_rc}"
}

collect_and_teardown() {
	rc=${1:-$?}
	[ -n "${_teardown_done:-}" ] && return 0
	_teardown_done=1

	if [ "${rc}" -ne 0 ]; then
		rescue_dir="${INFINITO_RESCUE_DIAGNOSTICS_BASE}/${INFINITO_DISTRO}/${APP_ID}"
		INFINITO_RESCUE_DIAGNOSTICS_DIR="${rescue_dir}" \
			run_within_deadline 1500 "$((collect_floor_seconds * 2 + index_floor_seconds * 2 + teardown_floor_seconds))" \
			python3 utils/diagnostics/container.py \
			"${APP_ID}" "post-deploy failure" || true # nocheck: shell-or-true -- best-effort diagnostics + teardown in the EXIT trap
		INFINITO_RESCUE_DIAGNOSTICS_DIR="${rescue_dir}" \
			run_within_deadline 900 "$((collect_floor_seconds + index_floor_seconds * 2 + teardown_floor_seconds))" \
			bash "${SCRIPT_DIR}/../utils/collect/diagnostics.sh" || true # nocheck: shell-or-true -- best-effort diagnostics + teardown in the EXIT trap
		run_within_deadline 300 "$((collect_floor_seconds + index_floor_seconds + teardown_floor_seconds))" \
			bash "${REPO_ROOT}/scripts/tests/deploy/utils/rescue_index.sh" "${rescue_dir}" || true # nocheck: shell-or-true -- best-effort diagnostics + teardown in the EXIT trap
	fi

	run_within_deadline 900 "$((index_floor_seconds + teardown_floor_seconds))" \
		bash "${SCRIPT_DIR}/../utils/collect/playwright_reports.sh" || true # nocheck: shell-or-true -- best-effort diagnostics + teardown in the EXIT trap
	run_within_deadline 300 "${teardown_floor_seconds}" \
		bash "${SCRIPT_DIR}/../utils/collect/topology_summary.sh" || true # nocheck: shell-or-true -- best-effort diagnostics + teardown in the EXIT trap
	run_within_deadline 900 0 \
		bash "${SCRIPT_DIR}/../utils/clean/teardown.sh" || true # nocheck: shell-or-true -- best-effort diagnostics + teardown in the EXIT trap

	return "${rc}"
}
trap collect_and_teardown EXIT
trap 'collect_and_teardown 143' TERM

# shellcheck source=scripts/tests/deploy/utils/filesystem/pick.sh
. "${REPO_ROOT}/scripts/tests/deploy/utils/filesystem/pick.sh"
filesystem_pick "swarm/${APP_ID}/${INFINITO_DISTRO}" node

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

step_timeout="$((INFINITO_SWARM_STEP_TIMEOUT_MINUTES * 60))"
if [ -n "${INFINITO_CI_DISTRO_DEADLINE_EPOCH:-}" ]; then                                                         # nocheck: distros.sh computes this epoch from the sweep budget at run time; a static default would be a stale timestamp
	under_governor="$((INFINITO_CI_DISTRO_DEADLINE_EPOCH - $(date +%s) - INFINITO_SWARM_TEARDOWN_RESERVE_SECONDS))" # nocheck: run-time state, not a configurable default
	if [ "${under_governor}" -le 0 ]; then
		echo "[ERROR] no budget left under the sweep governor for the matrix deploy" >&2
		exit 2
	fi
	if [ "${under_governor}" -lt "${step_timeout}" ]; then
		step_timeout="${under_governor}"
	fi
fi

matrix_cmd=(timeout "${step_timeout}" python3 -m utils.tests.swarm.matrix)
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
"${matrix_cmd[@]}"

bash "${SCRIPT_DIR}/05_seed_content.sh"
bash "${SCRIPT_DIR}/06_drain_worker.sh"
bash "${SCRIPT_DIR}/07_assert_state.sh"

echo "==> swarm drill complete: app=${APP_ID} distro=${INFINITO_DISTRO}"
