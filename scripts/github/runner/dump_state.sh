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

echo "--- disk (inodes) ---"
df -hi / /mnt 2>/dev/null || df -hi /

echo "--- block devices ---"
lsblk -f || true

echo "--- mounts (/, /mnt, /var/lib/docker, /mnt/docker) ---"
mount | grep -E ' / | /mnt | /var/lib/docker | /mnt/docker ' || true

echo "--- docker ---"
docker info 2>/dev/null |
	grep -E 'Docker Root Dir|Storage Driver|Containers|Images' ||
	echo "docker daemon not reachable"

echo "--- memory ---"
free -h

echo "--- swap ---"
swapon --show || echo "no swap active"

echo "--- largest dirs on / (top 15) ---"
sudo du -xh --max-depth=2 / 2>/dev/null | sort -h | tail -15 || true

if [ -d /mnt ]; then
	echo "--- largest dirs on /mnt (top 15) ---"
	sudo du -xh --max-depth=2 /mnt 2>/dev/null | sort -h | tail -15 || true
fi

# Nested view — hlth-disc-space runs INSIDE the infinito container and
# evaluates df there, so host-side df alone can be misleading. These
# blocks silently no-op when the container is not (yet) running.
echo "--- infinito container (nested view) ---"
INFINITO_CONTAINER="$(docker ps --filter 'name=infinito_nexus' --format '{{.Names}}' 2>/dev/null | head -1 || true)"
if [ -n "${INFINITO_CONTAINER}" ]; then
	echo "container: ${INFINITO_CONTAINER}"

	echo "--- df inside container ---"
	docker exec "${INFINITO_CONTAINER}" df -h 2>&1 || echo "docker exec df failed"

	echo "--- df --output=pcent inside container (what hlth-disc-space sees) ---"
	docker exec "${INFINITO_CONTAINER}" df --output=pcent 2>&1 || true

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
