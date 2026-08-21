#!/usr/bin/env bash
# Move the host Docker data-root onto /mnt when it is a separate, roomier
# partition. Image/volume storage (swarm's nested DinD-node daemons, the
# DR-drill LUKS loop image, per-node registry pulls) otherwise piles onto
# the ~50 GB root fs and trips the <6 GB abort guard in
# utils/tests/swarm/matrix.py. On public runners without a separate /mnt
# this is a no-op and Docker stays on /.
#
# Best-effort: relocation is an optimization, never a requirement. Any
# failure rolls Docker back onto / and the step still exits 0, so a hiccup
# here can never turn an otherwise-green deploy red. Runs BEFORE any Docker
# usage; the free-disk-space step already pruned the preinstalled images, so
# /var/lib/docker is ~empty and nothing is copied.
#
# Usage: relocate_docker_dataroot.sh [min-free-gb]
# Default floor: 40 GB (swarm peak footprint; below it /mnt buys nothing).
#
# Debug toggle: SKIP_DOCKER_RELOCATE=1 leaves the data-root on /.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUMP="${HERE}/dump_state.sh"

if [ "${SKIP_DOCKER_RELOCATE:-0}" = "1" ]; then
	echo "SKIP_DOCKER_RELOCATE=1 — leaving Docker data-root on /."
	"$DUMP" "docker-relocate skipped (SKIP_DOCKER_RELOCATE=1)"
	exit 0
fi

TARGET_DIR=/mnt/docker
MIN_FREE_GB="${1:-40}"

if ! mountpoint -q /mnt 2>/dev/null; then
	echo "/mnt is not a separate mount — leaving Docker data-root on /."
	"$DUMP" "docker-relocate skipped (no separate /mnt)"
	exit 0
fi

mnt_free=$(df --output=avail -B1G /mnt | tail -n1 | tr -d ' ')
root_free=$(df --output=avail -B1G / | tail -n1 | tr -d ' ')
echo "Free: / ${root_free}G, /mnt ${mnt_free}G; need >= ${MIN_FREE_GB}G on /mnt and roomier than /"

if [ "$mnt_free" -lt "$MIN_FREE_GB" ] || [ "$mnt_free" -le "$root_free" ]; then
	echo "/mnt below floor or not roomier than / — leaving Docker data-root on /."
	"$DUMP" "docker-relocate skipped (/mnt not roomier)"
	exit 0
fi

backup=""
if [ -s /etc/docker/daemon.json ]; then
	backup="$(mktemp)"
	cp /etc/docker/daemon.json "$backup"
fi

restore_and_continue() {
	echo "WARN: Docker data-root relocation failed — keeping Docker on /." >&2
	if [ -n "$backup" ]; then
		sudo install -m 0644 "$backup" /etc/docker/daemon.json || true # nocheck: shell-or-true -- rollback must reach the docker restart even if the restore fails
	else
		sudo rm -f /etc/docker/daemon.json || true # nocheck: shell-or-true -- rollback must reach the docker restart even if the cleanup fails
	fi
	sudo systemctl start docker.service || sudo systemctl restart docker.service || true # nocheck: shell-or-true -- last-ditch daemon start; rollback still exits 0 by design
	"$DUMP" "docker-relocate rolled back (kept on /)"
	exit 0
}

echo "Relocating Docker data-root to ${TARGET_DIR}"
sudo systemctl stop docker.service docker.socket || true # nocheck: shell-or-true -- inactive/missing units may exit non-zero; a wedged daemon is caught by the post-start root-dir check
sudo mkdir -p "$TARGET_DIR" /etc/docker || restore_and_continue

tmp="$(mktemp)"
if [ -n "$backup" ]; then
	jq --arg dr "$TARGET_DIR" '. + {"data-root": $dr}' "$backup" >"$tmp" || restore_and_continue
else
	printf '{"data-root": "%s"}\n' "$TARGET_DIR" >"$tmp"
fi
sudo install -m 0644 "$tmp" /etc/docker/daemon.json || restore_and_continue
rm -f "$tmp"

sudo systemctl start docker.service || restore_and_continue

root_dir=""
attempt=0
while [ "$attempt" -lt 30 ]; do
	root_dir="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
	[ -n "$root_dir" ] && break
	attempt=$((attempt + 1))
	sleep 1
done

if [ "$root_dir" != "$TARGET_DIR" ]; then
	echo "Docker came up with root '${root_dir}', expected '${TARGET_DIR}'." >&2
	restore_and_continue
fi

echo "Docker Root Dir: ${root_dir}"
[ -n "$backup" ] && rm -f "$backup"
"$DUMP" "after docker-relocate -> ${TARGET_DIR}"
