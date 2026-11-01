#!/usr/bin/env bash
# Drain the worker running the app and force a reschedule. The cluster runs
# without a registry and deploys with --resolve-image never, so a role that
# ships a build: context produces its <ENTITY>_custom:<tag> image only on the
# manager; mirror it onto each worker first so swarm can re-schedule there.
# Roles without a custom build use an upstream image present on every worker.
# The drained node is set active again once the app has moved: in an HA lab it
# can be a manager whose pinned database and etcd instances the drain stops.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../utils/_context.sh"

skip_if_no_swarm_service
skip_chaos_if_manager_pinned

[ -n "${INITIAL_NODE}" ] || {
	echo "INITIAL_NODE not set"
	exit 1
}

echo "==> Distributing ${CUSTOM_IMAGE_REPO} image to swarm workers"
IMAGE_TAG=$(docker exec "${MGR}" docker images --format '{{.Repository}}:{{.Tag}}' |
	grep "^${CUSTOM_IMAGE_REPO}:" | head -1 || true)
if [ -z "${IMAGE_TAG}" ]; then
	echo "    no '${CUSTOM_IMAGE_REPO}:*' image on manager — role uses an upstream image; skipping distribution"
else
	echo "    image: ${IMAGE_TAG}"
	# shellcheck disable=SC2086  # the lab worker list is space-separated words
	for worker in ${SWARM_LAB_WORKERS}; do
		echo "    -> ${worker}"
		docker exec "${MGR}" docker save "${IMAGE_TAG}" |
			docker exec -i "${worker}" docker load
	done
fi

# Param: $1 availability, $2 node
# Retries: swarm rejects a node update with "update out of sequence" when the
# node object changed between the CLI's read and its write.
set_availability() {
	local _try _err
	for _try in 1 2 3 4 5; do
		if _err="$(docker exec "${MGR}" docker node update --availability "$1" "$2" 2>&1)"; then
			return 0
		fi
		case "${_err}" in
		*"update out of sequence"*) sleep 2 ;;
		*)
			echo "FAILURE: could not set ${2} to ${1}: ${_err}"
			exit 1
			;;
		esac
	done
	echo "FAILURE: could not set ${2} to ${1} after ${_try} tries: ${_err}"
	exit 1
}

set_availability drain "${INITIAL_NODE}"

NEW_NODE=""
for i in $(seq 1 "${RESCHED_TIMEOUT}"); do
	NEW_NODE=$(docker exec "${MGR}" docker service ps \
		--filter desired-state=running \
		--format '{{.Node}}' "${SERVICE_NAME}" | head -1)
	if [ -n "${NEW_NODE}" ] && [ "${NEW_NODE}" != "${INITIAL_NODE}" ]; then
		echo "Rescheduled from ${INITIAL_NODE} to ${NEW_NODE} after ${i}s"
		echo "NEW_NODE=${NEW_NODE}" >>"${SWARM_DRILL_ENV:?SWARM_DRILL_ENV is required (exported by routine/00_one.sh)}"
		set_availability active "${INITIAL_NODE}"
		echo "${INITIAL_NODE} is active again"
		exit 0
	fi
	sleep 1
done

echo "FAILURE: ${ENTITY} did not migrate from ${INITIAL_NODE}"
docker exec "${MGR}" docker service ps "${SERVICE_NAME}"
exit 1
