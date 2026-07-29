#!/usr/bin/env bash
# shellcheck shell=bash
#
# Release the host-side NFS mount of the cluster-shared infinito state.
#
# `mountpoint` and `findmnt --mountpoint` block on a mount whose NFS server is
# gone, which is exactly the case this has to clean up, so detection reads
# /proc/self/mountinfo instead.
#
# Param:
#   $1  mount point of the shared state (DIR_VAR_LIB)

set -u

mount_point="${1:?mount point required}"

mounted() {
	grep -qF " ${mount_point} " /proc/self/mountinfo
}

mounted || exit 0

umount_cmd=(timeout 30 umount -lf "${mount_point}")
if [ "$(id -u)" -ne 0 ]; then
	umount_cmd=(sudo -n "${umount_cmd[@]}")
fi

echo ">>> releasing host NFS mount at ${mount_point}"
"${umount_cmd[@]}" 2>/dev/null

if mounted; then
	echo "FAILURE: ${mount_point} is still mounted; the next drill would inherit a stale NFS handle" >&2
	exit 1
fi
