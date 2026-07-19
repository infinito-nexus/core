#!/usr/bin/env bash
# Drain the worker running the app and force a reschedule. The cluster runs
# without a registry and deploys with --resolve-image never, so a role that
# ships a build: context produces its <ENTITY>_custom:<tag> image only on the
# manager; mirror it onto each worker first so swarm can re-schedule there.
# Roles without a custom build use an upstream image present on every worker.
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
	for worker in "${WRK1}" "${WRK2}"; do
		echo "    -> ${worker}"
		docker exec "${MGR}" docker save "${IMAGE_TAG}" |
			docker exec -i "${worker}" docker load
	done
fi

docker exec "${MGR}" docker node update --availability drain "${INITIAL_NODE}"

NEW_NODE=""
for i in $(seq 1 "${RESCHED_TIMEOUT}"); do
	NEW_NODE=$(docker exec "${MGR}" docker service ps \
		--filter desired-state=running \
		--format '{{.Node}}' "${SERVICE_NAME}" | head -1)
	if [ -n "${NEW_NODE}" ] && [ "${NEW_NODE}" != "${INITIAL_NODE}" ]; then
		echo "Rescheduled from ${INITIAL_NODE} to ${NEW_NODE} after ${i}s"
		echo "NEW_NODE=${NEW_NODE}" >>"$GITHUB_ENV"
		exit 0
	fi
	sleep 1
done

echo "FAILURE: ${ENTITY} did not migrate from ${INITIAL_NODE}"
docker exec "${MGR}" docker service ps "${SERVICE_NAME}"
exit 1
