#!/usr/bin/env bash
# Detach NFS client mounts inside live swarm-test containers before killing the
# NFS server or removing the containers. This prevents hard NFS mounts from
# retrying forever after their server disappears.
set -uo pipefail

NFS_UNMOUNT_TIMEOUT="${NFS_UNMOUNT_TIMEOUT:-10s}"

if [ "$#" -eq 0 ]; then
	exit 0
fi

for container in "$@"; do
	[ -n "${container}" ] || continue
	docker inspect "${container}" >/dev/null 2>&1 || continue

	echo ">>> swarm-cleanup: detach NFS mounts inside ${container}"
	if ! docker exec -e NFS_UNMOUNT_TIMEOUT="${NFS_UNMOUNT_TIMEOUT}" "${container}" sh -s <<'SH'; then
set -eu

mounts="$(
	awk '
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
			if (fstype ~ /^nfs/) {
				print unescape_mount($5)
			}
		}
	' /proc/self/mountinfo | sort -r
)"

[ -n "${mounts}" ] || exit 0

printf '%s\n' "${mounts}" | while IFS= read -r mount_point; do
	[ -n "${mount_point}" ] || continue
	echo "    detach ${mount_point}"
	if command -v timeout >/dev/null 2>&1; then
		timeout "${NFS_UNMOUNT_TIMEOUT}" umount -f -l -n -c "${mount_point}" 2>/dev/null ||
			timeout "${NFS_UNMOUNT_TIMEOUT}" umount -f -l "${mount_point}" 2>/dev/null ||
			timeout "${NFS_UNMOUNT_TIMEOUT}" umount -l "${mount_point}" 2>/dev/null ||
			true
	else
		umount -f -l -n -c "${mount_point}" 2>/dev/null ||
			umount -f -l "${mount_point}" 2>/dev/null ||
			umount -l "${mount_point}" 2>/dev/null ||
			true
	fi
done
SH
		echo "WARNING: could not inspect/unmount NFS mounts inside ${container}" >&2
	fi
done
