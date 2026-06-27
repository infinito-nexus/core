#!/usr/bin/env bash
# Recover NFS client mounts that live inside wedged act-swarm nfs-server
# container mount namespaces. This is the escape hatch for a hard NFS loopback
# mount whose server was killed before the client mount was detached.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

# shellcheck source=scripts/meta/env/load.sh
source "${ROOT_DIR}/scripts/meta/env/load.sh" >/dev/null 2>&1 || true

CID="${CID:-}"
NFS_MOUNT="${NFS_MOUNT:-}"
NFS_CLEAN_TIMEOUT="${NFS_CLEAN_TIMEOUT:-10s}"

_docker_ids() {
	if [ -n "${CID}" ]; then
		docker ps -aq --filter "id=${CID}" 2>/dev/null
		docker ps -aq --filter "name=${CID}" 2>/dev/null
		return
	fi

	if [ -n "${INFINITO_SWARM_TEST_LABEL:-}" ]; then
		docker ps -aq \
			--filter "label=${INFINITO_SWARM_TEST_LABEL}" \
			--filter "name=nfs-server" 2>/dev/null
	fi

	# Fallback for old leftovers created before the swarm label existed.
	docker ps -aq --filter "name=web-app-prometheus-nfs-server" 2>/dev/null
}

_container_name() {
	docker inspect -f '{{.Name}}' "$1" 2>/dev/null | sed 's#^/##' || true
}

_container_full_id() {
	docker inspect -f '{{.Id}}' "$1" 2>/dev/null || true
}

_container_state() {
	docker inspect -f 'status={{.State.Status}} pid={{.State.Pid}}' "$1" 2>/dev/null || true
}

_container_pids() {
	local container="$1"
	local full_id="$2"
	local pid

	pid="$(docker inspect -f '{{.State.Pid}}' "${container}" 2>/dev/null || true)"
	if [ -n "${pid}" ] && [ "${pid}" != "0" ]; then
		printf '%s\n' "${pid}"
	fi

	if [ -n "${full_id}" ]; then
		sudo grep -Els "${full_id}" /proc/[0-9]*/cgroup 2>/dev/null |
			sed -E 's#/proc/([0-9]+)/cgroup#\1#' || true
	fi
}

_nfs_mounts_for_pid() {
	local pid="$1"

	sudo awk -v requested="${NFS_MOUNT}" '
		function unescape_mount(s) {
			gsub(/\\040/, " ", s)
			gsub(/\\011/, "\t", s)
			gsub(/\\012/, "\n", s)
			gsub(/\\134/, "\\", s)
			return s
		}
		{
			sep = 0
			for (i = 1; i <= NF; i++) {
				if ($i == "-") {
					sep = i
					break
				}
			}
			fstype = sep > 0 && sep < NF ? $(sep + 1) : ""
			if (requested != "" && $5 == requested) {
				mounts[$5] = 1
			}
			if (fstype ~ /^nfs/) {
				mounts[$5] = 1
			}
		}
		END {
			for (mount_point in mounts) {
				print unescape_mount(mount_point)
			}
		}
	' "/proc/${pid}/mountinfo" 2>/dev/null || true
}

_detach_mounts_for_pid() {
	local pid="$1"
	local mount_point
	local mounts=()

	if [ ! -e "/proc/${pid}/ns/mnt" ]; then
		echo "    pid ${pid}: mount namespace is gone"
		return 0
	fi

	mapfile -t mounts < <(_nfs_mounts_for_pid "${pid}" | sort -u)
	if [ "${#mounts[@]}" -eq 0 ] && [ -n "${NFS_MOUNT}" ]; then
		mounts=("${NFS_MOUNT}")
	fi
	if [ "${#mounts[@]}" -eq 0 ]; then
		echo "    pid ${pid}: no nfs mounts found"
		return 0
	fi

	for mount_point in "${mounts[@]}"; do
		echo "    pid ${pid}: detach ${mount_point}"
		sudo timeout "${NFS_CLEAN_TIMEOUT}" umount -N "${pid}" -f -l -n -c "${mount_point}" 2>/dev/null ||
			sudo timeout "${NFS_CLEAN_TIMEOUT}" nsenter -t "${pid}" -m -- umount -f -l -n -c "${mount_point}" 2>/dev/null ||
			true
	done
}

_rm_container() {
	local container="$1"

	docker rm -fv "${container}" 2>&1 | sed 's/^/    /'
}

_force_reap_container() {
	local container="$1"
	local full_id="$2"
	local short_id="${full_id:0:12}"
	local pid
	local pids=()

	echo ">>> stale-nfs: force-reap ${container}"
	mapfile -t pids < <(_container_pids "${container}" "${full_id}" | sort -u)
	for pid in "${pids[@]}"; do
		echo "    kill pid ${pid}"
		sudo kill -9 "${pid}" 2>/dev/null || true
		sudo pkill -9 -P "${pid}" 2>/dev/null || true
	done

	if [ -n "${full_id}" ]; then
		sudo pkill -9 -f "containerd-shim.*(${full_id}|${short_id})" 2>/dev/null || true
	fi
}

containers="$(_docker_ids | sort -u | sed '/^$/d')"
if [ -z "${containers}" ]; then
	echo ">>> stale-nfs: no nfs-server containers found"
	echo "    usage: make clean-stale-nfs [cid=<container-id-or-name>] [mount=/mnt/gtest]"
	exit 0
fi

echo ">>> stale-nfs: candidate containers"
while IFS= read -r container; do
	[ -n "${container}" ] || continue
	printf '    %s\n' "${container}"
done <<<"${containers}"

survivors=()
for container in ${containers}; do
	full_id="$(_container_full_id "${container}")"
	name="$(_container_name "${container}")"
	state="$(_container_state "${container}")"
	echo ">>> stale-nfs: inspect ${container} ${name:+(${name})} ${state}"

	mapfile -t pids < <(_container_pids "${container}" "${full_id}" | sort -u)
	if [ "${#pids[@]}" -eq 0 ]; then
		echo "    no host pids found"
	else
		for pid in "${pids[@]}"; do
			_detach_mounts_for_pid "${pid}"
		done
	fi

	if ! _rm_container "${container}"; then
		survivors+=("${container}:${full_id}")
	fi
done

if [ "${#survivors[@]}" -eq 0 ]; then
	echo ">>> stale-nfs: done"
	exit 0
fi

echo ">>> stale-nfs: docker rm did not reap every container; escalating to shim/task cleanup"
for survivor in "${survivors[@]}"; do
	container="${survivor%%:*}"
	full_id="${survivor#*:}"
	_force_reap_container "${container}" "${full_id}"
done

echo ">>> stale-nfs: restart containerd/docker"
sudo systemctl restart containerd docker || sudo systemctl restart docker

failed=0
for survivor in "${survivors[@]}"; do
	container="${survivor%%:*}"
	if ! _rm_container "${container}"; then
		failed=1
	fi
done

if [ "${failed}" -eq 0 ]; then
	echo ">>> stale-nfs: done"
	exit 0
fi

echo "!!! stale-nfs: one or more containers still survived"
echo "!!! If their tasks are in real kernel D-state, only fixing the backing I/O/NFS server or a host reboot can release them."
exit 1
