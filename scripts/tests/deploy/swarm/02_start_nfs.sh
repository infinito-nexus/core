#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${RUNNER_TEMP}/nfs-export"
docker run -d --name "${NFS_SERVER}" \
	--network swarm-lab \
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
	-v "${RUNNER_TEMP}/nfs-export:/srv/nfs" \
	jrei/systemd-ubuntu:24.04

SYSTEMD_TIMEOUT="${SWARM_PILOT_SYSTEMD_TIMEOUT:-180}"
for i in $(seq 1 "${SYSTEMD_TIMEOUT}"); do
	if docker exec "${NFS_SERVER}" systemctl is-system-running 2>/dev/null |
		grep -qE 'running|degraded|starting|maintenance'; then
		echo "systemd ready on ${NFS_SERVER} after ${i}s"
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
