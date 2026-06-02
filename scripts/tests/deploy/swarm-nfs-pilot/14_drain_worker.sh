#!/usr/bin/env bash
set -euo pipefail

[ -n "${INITIAL_NODE}" ] || {
	echo "INITIAL_NODE not set"
	exit 1
}

# No registry + --resolve-image never: workers need the image pushed manually.
echo "==> Distributing mediawiki_custom image to swarm workers"
IMAGE_TAG=$(docker exec "${MGR}" docker images --format '{{.Repository}}:{{.Tag}}' |
	grep '^mediawiki_custom:' | head -1)
[ -n "${IMAGE_TAG}" ] || {
	echo "FAILURE: mediawiki_custom image not present on manager"
	exit 1
}
echo "    image: ${IMAGE_TAG}"
for worker in "${WRK1}" "${WRK2}"; do
	echo "    -> ${worker}"
	docker exec "${MGR}" docker save "${IMAGE_TAG}" |
		docker exec -i "${worker}" docker load
done

docker exec "${MGR}" docker node update --availability drain "${INITIAL_NODE}"

NEW_NODE=""
for i in $(seq 1 "${RESCHED_TIMEOUT}"); do
	NEW_NODE=$(docker exec "${MGR}" docker service ps \
		--filter desired-state=running \
		--format '{{.Node}}' "${STACK_NAME}_mediawiki" | head -1)
	if [ -n "${NEW_NODE}" ] && [ "${NEW_NODE}" != "${INITIAL_NODE}" ]; then
		echo "Rescheduled from ${INITIAL_NODE} to ${NEW_NODE} after ${i}s"
		echo "NEW_NODE=${NEW_NODE}" >>"$GITHUB_ENV"
		exit 0
	fi
	sleep 1
done

echo "FAILURE: MediaWiki did not migrate from ${INITIAL_NODE}"
docker exec "${MGR}" docker service ps "${STACK_NAME}_mediawiki"
exit 1
