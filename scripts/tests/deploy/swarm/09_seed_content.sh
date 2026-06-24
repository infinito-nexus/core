#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"

skip_if_no_swarm_service
skip_chaos_if_manager_pinned

# Drain a WORKER running the app, never the manager: the manager pins the
# registry, DB and edge proxy, so draining it kills services the rescheduled
# task depends on (and they cannot move). Worker failure is the recoverable
# scenario this chaos test targets.
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
		"echo 'pre-drain marker' > ${NFS_EXPORT_BASE}/${PRIMARY_NFS_VOLUME}/.pre-drain"
else
	echo "Role '${APP_ID}' declares no NFS-flagged volume in meta/volumes.yml — skipping NFS marker seed"
fi

# Swarm routing-mesh ingress is broken in DinD-on-DinD (no iptables/VXLAN);
# probe the app directly inside its task container.
APP_CTR=$(docker exec "${NODE}" docker ps \
	--filter "name=${SERVICE_NAME}" \
	--format '{{.ID}}' | head -1)
if [ -z "${APP_CTR}" ]; then
	echo "FAILURE: cannot locate ${ENTITY} container on ${NODE}"
	exit 1
fi
for i in $(seq 1 30); do
	# No -f: many app roots legitimately 404 (UI/API live elsewhere); we only
	# assert the HTTP server responds, not that '/' is 2xx.
	if docker exec "${NODE}" docker exec "${APP_CTR}" \
		curl -sS "http://localhost:${PROBE_PORT}/" >/dev/null 2>&1; then
		echo "${ENTITY} HTTP reachable inside container after ${i}s"
		break
	fi
	sleep 2
done
