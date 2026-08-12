#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../utils/_context.sh"

skip_if_no_swarm_service
skip_chaos_if_manager_pinned

REPL=""
for i in $(seq 1 120); do
	REPL=$(service_replicas "${MGR}" "${SERVICE_NAME}")
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
    mkdir -p ${NFS_CHECK_MOUNTPOINT}
    mount -t nfs4 -o vers=4 ${NFS_IP}:${NFS_STATE_PATH} ${NFS_CHECK_MOUNTPOINT} \
      || mount -t nfs4 -o vers=4 ${NFS_IP}:/ ${NFS_CHECK_MOUNTPOINT} \
      || mount -t nfs -o vers=3,nolock ${NFS_IP}:${NFS_STATE_PATH} ${NFS_CHECK_MOUNTPOINT} \
      || exit 1
    grep -q 'pre-drain marker' ${NFS_CHECK_MOUNTPOINT}/${PRIMARY_NFS_VOLUME}/.pre-drain
    rc=\$?
    umount ${NFS_CHECK_MOUNTPOINT}
    exit \$rc
  " || {
		echo "FAILURE: marker missing on NFS volume '${PRIMARY_NFS_VOLUME}'"
		exit 1
	}
else
	echo "No NFS-flagged volume for '${APP_ID}' — skipping NFS marker assertion"
fi

APP_CTR=$(service_container_id "${NEW_NODE}" "${SERVICE_NAME}")
if [ -z "${APP_CTR}" ]; then
	echo "FAILURE: cannot locate ${ENTITY} container on ${NEW_NODE}"
	exit 1
fi
DRILL_MIN_WAIT_SECONDS=60
DECLARED_READY_SECONDS=$(docker exec "${NEW_NODE}" docker inspect "${APP_CTR}" 2>/dev/null |
	awk '
		/"Healthcheck": \{/ { inhc = 1 }
		inhc && /"StartPeriod":/ { gsub(/[^0-9]/, "", $2); sp = $2 }
		inhc && /"Interval":/    { gsub(/[^0-9]/, "", $2); iv = $2 }
		inhc && /"Retries":/     { gsub(/[^0-9]/, "", $2); rt = $2; inhc = 0 }
		END {
			budget = 0
			if (sp != "" && iv != "" && rt != "") {
				budget = int(sp / 1000000000) + int(iv / 1000000000) * rt
			}
			print budget
		}')
READY_BUDGET=$((DECLARED_READY_SECONDS > DRILL_MIN_WAIT_SECONDS ? DECLARED_READY_SECONDS : DRILL_MIN_WAIT_SECONDS))
echo "waiting up to ${READY_BUDGET}s for ${ENTITY} to answer on ${NEW_NODE} (declared ${DECLARED_READY_SECONDS}s)"
for _ in $(seq 1 $((READY_BUDGET / 2))); do
	if probe_app_reachable "${NEW_NODE}" "${APP_CTR}" "${PROBE_PORT}"; then
		echo "${ENTITY} reachable after reschedule"
		exit 0
	fi
	sleep 2
done
echo "FAILURE: ${ENTITY} not reachable after reschedule within ${READY_BUDGET}s"
exit 1
