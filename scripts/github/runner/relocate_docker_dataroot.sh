#!/usr/bin/env bash
# Usage: relocate_docker_dataroot.sh MIN_FREE_GB
#   MIN_FREE_GB             smallest free space on /mnt that makes the move worth it
#   SKIP_DOCKER_RELOCATE=1  leave Docker and containerd on /
set -euo pipefail

MIN_FREE_GB="${1:?MIN_FREE_GB is required - state the smallest free GB on /mnt worth relocating to at the call site}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUMP="${HERE}/dump_state.sh"

DATA_ROOT=/mnt/docker-host
CONTAINERD_ROOT=/var/lib/containerd
CONTAINERD_TARGET=/mnt/containerd
DAEMON_JSON=/etc/docker/daemon.json

# Param: $1 why Docker and containerd stay on /
decline() {
	echo "::notice::relocate_docker_dataroot.sh left Docker and containerd on /: $1"
	"$DUMP" "docker-relocate skipped ($1)"
	exit 0
}

# Param: $1 what was found that the relocation would lose or orphan
refuse() {
	echo "::error::relocate_docker_dataroot.sh refuses to move Docker and containerd: $1" >&2
	exit 1
}

if [ "${SKIP_DOCKER_RELOCATE:-0}" = "1" ]; then
	decline "SKIP_DOCKER_RELOCATE=1"
fi

if [ -n "${ACT:-}" ]; then
	echo "::error::relocate_docker_dataroot.sh refuses to run under act (ACT=${ACT}): it restarts Docker and containerd and must never touch the operator's machine" >&2
	exit 1
fi

if ! [[ "${MIN_FREE_GB}" =~ ^[1-9][0-9]*$ ]]; then
	echo "::error::MIN_FREE_GB must be a positive integer, got '${MIN_FREE_GB}'" >&2
	exit 1
fi

if [ "${RUNNER_ENVIRONMENT:-}" != github-hosted ]; then
	echo "::notice::relocate_docker_dataroot.sh left Docker and containerd where they are: not a GitHub-hosted runner (RUNNER_ENVIRONMENT='${RUNNER_ENVIRONMENT:-}')"
	exit 0
fi

if ! mountpoint -q /mnt; then
	decline "/mnt is not a separate mount"
fi

mnt_free=$(df --output=avail -B1G /mnt | tail -n1 | tr -d ' ')
root_free=$(df --output=avail -B1G / | tail -n1 | tr -d ' ')
echo "Free: / ${root_free}G, /mnt ${mnt_free}G; need >= ${MIN_FREE_GB}G on /mnt and roomier than /"

if [ "$mnt_free" -lt "$MIN_FREE_GB" ]; then
	decline "/mnt has ${mnt_free}G free, below ${MIN_FREE_GB}G"
fi
if [ "$mnt_free" -le "$root_free" ]; then
	decline "/mnt has ${mnt_free}G free, not more than the ${root_free}G on /"
fi

if ! systemctl cat containerd.service >/dev/null; then
	refuse "containerd.service is missing"
fi

configured_root="$(sudo containerd config dump | sed -nE "s/^root = ['\"](.*)['\"]\$/\1/p")"
if [ "${configured_root}" != "${CONTAINERD_ROOT}" ]; then
	refuse "containerd root is '${configured_root}', expected ${CONTAINERD_ROOT}"
fi

containers="$(docker ps -aq)"
[ -z "${containers}" ] || refuse "Docker containers exist: ${containers//$'\n'/ }"
images="$(docker images -q)"
[ -z "${images}" ] || refuse "Docker images exist: ${images//$'\n'/ }"
volumes="$(docker volume ls -q)"
[ -z "${volumes}" ] || refuse "Docker volumes exist: ${volumes//$'\n'/ }"
build_cache="$(docker system df --format '{{.Type}}={{.TotalCount}}' | sed -n 's/^Build Cache=//p')"
[ "${build_cache}" = 0 ] || refuse "the build cache holds '${build_cache}' records"

namespaces="$(sudo ctr namespaces ls -q)"
for namespace in ${namespaces}; do
	[ "${namespace}" != moby ] || continue
	foreign="$(sudo ctr -n "${namespace}" containers ls -q)"
	[ -z "${foreign}" ] || refuse "containerd namespace ${namespace} holds containers: ${foreign//$'\n'/ }"
	tasks="$(sudo ctr -n "${namespace}" tasks ls -q)"
	[ -z "${tasks}" ] || refuse "containerd namespace ${namespace} runs tasks: ${tasks//$'\n'/ }"
done

shim_rc=0
shims="$(pgrep -a containerd-shim)" || shim_rc=$?
case "${shim_rc}" in
0) refuse "containerd shims are running: ${shims//$'\n'/; }" ;;
1) ;;
*) refuse "pgrep could not list containerd shims (rc=${shim_rc})" ;;
esac

sudo true
daemon_backup="$(mktemp)"
daemon_new="$(mktemp)"
if sudo test -e "${DAEMON_JSON}"; then
	daemon_existed=yes
	# shellcheck disable=SC2024
	sudo cat "${DAEMON_JSON}" >"${daemon_backup}"
	if [ -s "${daemon_backup}" ] && ! jq empty "${daemon_backup}"; then
		refuse "${DAEMON_JSON} is not valid JSON"
	fi
else
	daemon_existed=no
fi
if [ -s "${daemon_backup}" ]; then
	jq --arg dr "${DATA_ROOT}" '. + {"data-root": $dr}' "${daemon_backup}" >"${daemon_new}"
else
	jq -n --arg dr "${DATA_ROOT}" '{"data-root": $dr}' >"${daemon_new}"
fi

left_behind="$(sudo du -sxh "${CONTAINERD_ROOT}")"
echo "Left behind on /: ${left_behind%%[[:space:]]*} in ${CONTAINERD_ROOT}"
echo "Relocating the Docker data-root to ${DATA_ROOT} and the containerd root to ${CONTAINERD_TARGET}"

# Param: $1 what failed
rollback() {
	trap - ERR INT TERM
	set +e
	echo "::error::relocation failed ($1); rolling Docker and containerd back onto /" >&2
	if ! sudo systemctl stop docker.socket docker.service containerd.service; then
		echo "::error::could not stop Docker and containerd for the rollback" >&2
	fi
	if mountpoint -q "${CONTAINERD_ROOT}" && ! sudo umount "${CONTAINERD_ROOT}"; then
		echo "::error::could not unmount the bind over ${CONTAINERD_ROOT}" >&2
	fi
	if [ "${daemon_existed}" = yes ]; then
		if ! sudo install -m 0644 "${daemon_backup}" "${DAEMON_JSON}"; then
			echo "::error::could not restore ${DAEMON_JSON}" >&2
		fi
	elif ! sudo rm -f "${DAEMON_JSON}"; then
		echo "::error::could not remove the ${DAEMON_JSON} this script wrote" >&2
	fi
	if ! sudo systemctl start containerd.service docker.socket docker.service; then
		echo "::error::Docker or containerd did not come back up" >&2
	fi
	sudo systemctl status --no-pager containerd.service docker.service >&2
	sudo journalctl --no-pager -n 80 -u containerd.service -u docker.service >&2
	exit 1
}

trap 'rollback "command failed: ${BASH_COMMAND}"' ERR
trap 'rollback "interrupted"' INT TERM
sudo systemctl stop docker.socket docker.service containerd.service
sudo mkdir -p "${DATA_ROOT}" "${CONTAINERD_TARGET}" "$(dirname "${DAEMON_JSON}")"
sudo mount --bind "${CONTAINERD_TARGET}" "${CONTAINERD_ROOT}"
sudo install -m 0644 "${daemon_new}" "${DAEMON_JSON}"
sudo systemctl start containerd.service
sudo systemctl start docker.socket docker.service
sudo ctr version >/dev/null

if ! sudo test -f "${CONTAINERD_TARGET}/io.containerd.metadata.v1.bolt/meta.db"; then
	rollback "containerd came up without its metadata in ${CONTAINERD_TARGET}"
fi
root_dir="$(docker info --format '{{.DockerRootDir}}')"
if [ "${root_dir}" != "${DATA_ROOT}" ]; then
	rollback "Docker came up with root '${root_dir}', expected '${DATA_ROOT}'"
fi
mnt_dev="$(stat -c %d /mnt)"
if [ "$(stat -c %d "${root_dir}")" != "${mnt_dev}" ]; then
	rollback "Docker root ${root_dir} is not on the /mnt filesystem"
fi

trap - ERR INT TERM
rm -f "${daemon_backup}" "${daemon_new}"
echo "Docker Root Dir: ${root_dir}; containerd root ${CONTAINERD_ROOT} bound from ${CONTAINERD_TARGET}"
"$DUMP" "after docker-relocate -> ${DATA_ROOT}, containerd -> ${CONTAINERD_TARGET}"
