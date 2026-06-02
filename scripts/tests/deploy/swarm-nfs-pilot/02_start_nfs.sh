#!/usr/bin/env bash
set -euo pipefail

# Kernel NFS server cannot export overlay2 paths; bind-mount from a real fs.
mkdir -p "${RUNNER_TEMP}/nfs-export"
docker run -d --name "${NFS_SERVER}" \
	--network swarm-lab \
	--hostname "${NFS_SERVER}" \
	--privileged \
	--tmpfs /run \
	--tmpfs /run/lock \
	--tmpfs /tmp:exec \
	-v /sys/fs/cgroup:/sys/fs/cgroup:rw \
	-v /lib/modules:/lib/modules:ro \
	-v "${RUNNER_TEMP}/nfs-export:/srv/nfs" \
	jrei/systemd-ubuntu:24.04

for i in $(seq 1 60); do
	if docker exec "${NFS_SERVER}" systemctl is-system-running 2>/dev/null |
		grep -qE 'running|degraded|starting|maintenance'; then
		echo "systemd ready on ${NFS_SERVER} after ${i}s"
		exit 0
	fi
	sleep 1
done
echo "FAILURE: ${NFS_SERVER} systemd did not become responsive"
exit 1
