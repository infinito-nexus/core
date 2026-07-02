#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"

skip_if_no_swarm_service
skip_chaos_if_manager_pinned

REPL=""
for i in $(seq 1 60); do
	REPL=$(docker exec "${MGR}" docker service ls \
		--filter "name=${SERVICE_NAME}" --format '{{.Replicas}}')
	echo "[${i}] ${ENTITY} replicas: ${REPL}"
	if echo "${REPL}" | grep -qE '^([0-9]+)/\1$'; then
		break
	fi
	sleep 2
done
echo "${REPL}" | grep -qE '^([0-9]+)/\1$' || {
	echo "Replicas not fully converged: ${REPL}"
	exit 1
}

if [ -n "${PRIMARY_NFS_VOLUME}" ]; then
	docker exec "${NEW_NODE}" sh -c "
    mkdir -p /mnt/nfs-check
    mount -t nfs -o vers=3,nolock ${NFS_IP}:${NFS_STATE_PATH} /mnt/nfs-check
    grep -q 'pre-drain marker' /mnt/nfs-check/${PRIMARY_NFS_VOLUME}/.pre-drain
    umount /mnt/nfs-check
  " || {
		echo "FAILURE: marker missing on NFS volume '${PRIMARY_NFS_VOLUME}'"
		exit 1
	}
else
	echo "No NFS-flagged volume for '${APP_ID}' — skipping NFS marker assertion"
fi

APP_CTR=$(docker exec "${NEW_NODE}" docker ps \
	--filter "name=${SERVICE_NAME}" \
	--format '{{.ID}}' | head -1)
if [ -z "${APP_CTR}" ]; then
	echo "FAILURE: cannot locate ${ENTITY} container on ${NEW_NODE}"
	exit 1
fi
for i in $(seq 1 30); do
	if docker exec "${NEW_NODE}" docker exec "${APP_CTR}" sh -c \
		"curl -sS http://localhost:${PROBE_PORT}/ || wget -qO- http://localhost:${PROBE_PORT}/ || bash -c 'exec 3<>/dev/tcp/localhost/${PROBE_PORT}'" >/dev/null 2>&1; then
		echo "${ENTITY} reachable after reschedule"
		exit 0
	fi
	sleep 2
done
echo "FAILURE: ${ENTITY} not reachable after reschedule"
exit 1
