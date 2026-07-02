#!/usr/bin/env bash
set -euo pipefail

# Trip-wire: wipe stale state below as root inside the privileged container, not
# here - this (often non-root) act runner cannot delete the prior run's root-owned
# NFS writes (e.g. a root-owned matomo config.ini.php that then deadlocks redeploy).
bash "$(dirname "$0")/unmount_nfs_mounts.sh" "${NFS_SERVER}" >/dev/null 2>&1 || true
docker rm -f "${NFS_SERVER}" >/dev/null 2>&1 || true
mkdir -p "${RUNNER_TEMP}/nfs-export"

pull_attempts=3
for attempt in $(seq 1 "${pull_attempts}"); do
	docker pull jrei/systemd-ubuntu:24.04 && break
	if [ "${attempt}" -eq "${pull_attempts}" ]; then
		echo "FAILURE: docker pull jrei/systemd-ubuntu:24.04 failed after ${pull_attempts} attempts" >&2
		exit 1
	fi
	sleep $((attempt * 5))
done

docker run -d --name "${NFS_SERVER}" \
	--label "${INFINITO_SWARM_TEST_LABEL}" \
	--network "${SWARM_LAB_NETWORK}" \
	--hostname "${NFS_SERVER}" \
	--privileged \
	--cgroupns=host \
	--security-opt seccomp=unconfined \
	--security-opt apparmor=unconfined \
	--tmpfs /run \
	--tmpfs /run/lock \
	--tmpfs /tmp:exec \
	-v /sys/fs/cgroup:/sys/fs/cgroup:rw \
	-v /lib/modules:/lib/modules:ro \
	-v "${RUNNER_TEMP}/nfs-export:${NFS_EXPORT_BASE}" \
	jrei/systemd-ubuntu:24.04

SYSTEMD_TIMEOUT="${SWARM_PILOT_SYSTEMD_TIMEOUT:-180}"
for i in $(seq 1 "${SYSTEMD_TIMEOUT}"); do
	if docker exec "${NFS_SERVER}" systemctl is-system-running 2>/dev/null |
		grep -qE 'running|degraded|starting|maintenance'; then
		echo "systemd ready on ${NFS_SERVER} after ${i}s"
		docker exec "${NFS_SERVER}" find "${NFS_EXPORT_BASE}" -mindepth 1 -delete 2>/dev/null || true
		exit 0
	fi
	sleep 1
done
echo "FAILURE: ${NFS_SERVER} systemd did not become responsive within ${SYSTEMD_TIMEOUT}s"
echo "--- docker logs ${NFS_SERVER} ---"
docker logs "${NFS_SERVER}" 2>&1 || true
echo "--- last 50 journalctl lines from ${NFS_SERVER} ---"
docker exec "${NFS_SERVER}" journalctl --no-pager -n 50 2>&1 || true
echo "--- systemctl list-jobs ---"
docker exec "${NFS_SERVER}" systemctl list-jobs --no-pager 2>&1 || true
echo "--- docker inspect ${NFS_SERVER} (State) ---"
docker inspect --format '{{json .State}}' "${NFS_SERVER}" 2>&1 || true
exit 1
