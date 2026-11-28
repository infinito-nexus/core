#!/usr/bin/env bash
# Dump disk, memory, swap and docker state of a GitHub-hosted runner.
# Intended as a diagnostic helper that can be called from anywhere
# inside a workflow step (pre/post swap resize, post-deploy failure).
#
# Usage: dump_state.sh [label]
# The label is rendered into the log group title and the step summary.

set -euo pipefail

LABEL="${1:-runner state}"

echo "::group::Runner state — ${LABEL}"

echo "--- date ---"
date -u +'%Y-%m-%dT%H:%M:%SZ'

echo "--- disk (bytes) ---"
df -h / /mnt 2>/dev/null || df -h /

echo "--- disk per storage root (/, /mnt, containerd root, Docker data root) ---"
docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)" || docker_root=""
df -h --output=source,size,used,avail,target / /mnt /var/lib/containerd ${docker_root:+"${docker_root}"} ||
	echo "df could not read every storage root"

containerd --version 2>/dev/null || echo "containerd not on PATH"

echo "--- disk (inodes) ---"
df -hi / /mnt 2>/dev/null || df -hi /

echo "--- disks (bytes, model: Amazon EC2 NVMe Instance Storage versus Amazon Elastic Block Store) ---"
lsblk -d -b -o NAME,SIZE,MODEL,ROTA,TYPE || echo "lsblk could not list the disks"

echo "--- block devices ---"
lsblk -o NAME,TYPE,SIZE,FSTYPE,FSVER,LABEL,UUID,FSAVAIL,FSUSE%,MOUNTPOINTS || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

echo "--- mounts (/, /mnt, /var/lib/docker, /var/lib/containerd, /mnt/docker) ---"
mount | grep -E ' / | /mnt | /var/lib/docker | /var/lib/containerd | /mnt/docker ' || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

echo "--- docker ---"
docker info 2>/dev/null |
	grep -E 'Docker Root Dir|Storage Driver|Containers|Images' ||
	echo "docker daemon not reachable"

echo "--- memory ---"
free -h

echo "--- swap ---"
swapon --show || echo "no swap active"

# Param: $1 directory whose 15 largest subdirectories, two levels deep, are printed
# A serial du over a cold runner disk took 48.8 s of a 59.6 s dump, waiting on
# one metadata read at a time. Parallel du runs over the second level fill the
# inode cache first, so the unchanged serial du below reads warm (1.6 s).
largest_dirs() {
	if ! sudo find "$1" -mindepth 2 -maxdepth 2 -xdev -type d -print0 2>/dev/null |
		sudo xargs -0 -r -n 1 -P "$(($(nproc) * 4))" du -xs >/dev/null 2>&1; then
		echo "the parallel warm-up of $1 hit an unreadable entry; the listing below stays exact"
	fi
	sudo du -xh --max-depth=2 "$1" 2>/dev/null | sort -h | tail -15 || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
}

echo "--- largest dirs on / (top 15) ---"
largest_dirs /

if [ -d /mnt ]; then
	echo "--- largest dirs on /mnt (top 15) ---"
	largest_dirs /mnt
fi

echo "--- infinito container (nested view) ---"
INFINITO_CONTAINER="$(docker ps --filter 'name=infinito_nexus' --format '{{.Names}}' 2>/dev/null | head -1 || true)"
if [ -n "${INFINITO_CONTAINER}" ]; then
	echo "container: ${INFINITO_CONTAINER}"

	echo "--- df inside container ---"
	docker exec "${INFINITO_CONTAINER}" df -h 2>&1 || echo "docker exec df failed"

	echo "--- df --output=pcent inside container (what hlth-disc-space sees) ---"
	docker exec "${INFINITO_CONTAINER}" df --output=pcent 2>&1 || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

	echo "--- failed systemd units inside container ---"
	docker exec "${INFINITO_CONTAINER}" systemctl --failed --no-pager 2>&1 ||
		echo "systemctl --failed not reachable"

	echo "--- hlth-disc-space status ---"
	docker exec "${INFINITO_CONTAINER}" \
		systemctl status 'hlth-disc-space*' --no-pager -l 2>&1 ||
		echo "no hlth-disc-space unit (not deployed yet)"

	echo "--- hlth-disc-space journal (last 80 lines) ---"
	docker exec "${INFINITO_CONTAINER}" \
		journalctl -u 'hlth-disc-space*' -n 80 --no-pager 2>&1 ||
		echo "journal for hlth-disc-space not accessible"
else
	echo "no infinito container running (expected before 'make compose-up')"
fi

echo "::endgroup::"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
	root_free=$(df --output=avail -B1G / 2>/dev/null | tail -n1 | tr -d ' ' || echo '?')
	mnt_free=$(df --output=avail -B1G /mnt 2>/dev/null | tail -n1 | tr -d ' ' || echo '?')
	mem_free=$(free -g | awk '/^Mem:/ {print $4"G"}')
	swap_total=$(free -g | awk '/^Swap:/ {print $2"G"}')
	{
		echo "### Runner state — ${LABEL}"
		echo "- / free: **${root_free}G** · /mnt free: **${mnt_free}G**"
		echo "- mem free: **${mem_free}** · swap total: **${swap_total}**"
	} >>"$GITHUB_STEP_SUMMARY"
fi
