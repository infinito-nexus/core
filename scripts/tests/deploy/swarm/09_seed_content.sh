#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"

skip_if_no_swarm_service
skip_chaos_if_manager_pinned

# task depends on (and they cannot move). Worker failure is the recoverable
NODE=$(docker exec "${MGR}" sh -c "
  docker service ps --no-trunc \
    --format '{{.Node}} {{.CurrentState}}' \
    ${SERVICE_NAME} \
  | awk '\$2 == \"Running\" { print \$1 }'
" | grep -vx "${MGR}" | head -1 || true)
if [ -z "${NODE}" ]; then
	echo "FAILURE: no running ${ENTITY} task on a worker node"
	docker exec "${MGR}" docker service ps "${SERVICE_NAME}"
	exit 1
fi
echo "${ENTITY} initially scheduled on: ${NODE}"
echo "INITIAL_NODE=${NODE}" >>"$GITHUB_ENV"

if [ -n "${PRIMARY_NFS_VOLUME}" ]; then
	echo "Seeding pre-drain marker on NFS volume '${PRIMARY_NFS_VOLUME}'"
	docker exec "${NFS_SERVER}" sh -c \
		"echo 'pre-drain marker' > ${NFS_STATE_PATH}/${PRIMARY_NFS_VOLUME}/.pre-drain"
else
	echo "Role '${APP_ID}' declares no NFS-flagged volume in meta/volumes.yml — skipping NFS marker seed"
fi

APP_CTR=$(docker exec "${NODE}" docker ps \
	--filter "name=${SERVICE_NAME}" \
	--format '{{.ID}}' | head -1)
if [ -z "${APP_CTR}" ]; then
	echo "FAILURE: cannot locate ${ENTITY} container on ${NODE}"
	exit 1
fi
for i in $(seq 1 30); do
	if docker exec "${NODE}" docker exec "${APP_CTR}" sh -c \
		"curl -sS http://localhost:${PROBE_PORT}/ || wget -qO- http://localhost:${PROBE_PORT}/ || bash -c 'exec 3<>/dev/tcp/localhost/${PROBE_PORT}'" >/dev/null 2>&1; then
		echo "${ENTITY} HTTP reachable inside container after ${i}s"
		break
	fi
	sleep 2
done
