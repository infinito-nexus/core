#!/usr/bin/env bash
# Usage: mount_spare_disk.sh MOUNT_POINT MIN_SIZE_GB
#   MOUNT_POINT  where the spare disk lands; enlarge_swap.sh and
#                relocate_docker_dataroot.sh pick it up when it is /mnt
#   MIN_SIZE_GB  smallest spare disk worth mounting; smaller disks leave the runner as it is
set -euo pipefail

MOUNT_POINT="${1:?MOUNT_POINT is required - state where the spare disk is mounted at the call site}"
MIN_SIZE_GB="${2:?MIN_SIZE_GB is required - state the smallest spare disk in GB worth mounting at the call site}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUMP="${HERE}/dump_state.sh"

if [ -n "${ACT:-}" ]; then
	echo "::error::mount_spare_disk.sh refuses to run under act (ACT=${ACT}): it formats block devices and must never touch the operator's machine" >&2
	exit 1
fi

if ! [[ "${MIN_SIZE_GB}" =~ ^[1-9][0-9]*$ ]]; then
	echo "::error::MIN_SIZE_GB must be a positive integer, got '${MIN_SIZE_GB}'" >&2
	exit 1
fi

if [ "${RUNNER_ENVIRONMENT:-}" != github-hosted ]; then
	echo "::notice::mount_spare_disk.sh mounted no spare disk: not a GitHub-hosted runner (RUNNER_ENVIRONMENT='${RUNNER_ENVIRONMENT:-}'), every block device stays untouched"
	exit 0
fi

if mountpoint -q "${MOUNT_POINT}"; then
	echo "::notice::mount_spare_disk.sh mounted no spare disk: ${MOUNT_POINT} is already a separate mount"
	exit 0
fi

if [ ! -d "${MOUNT_POINT}" ]; then
	echo "::error::mount point ${MOUNT_POINT} does not exist" >&2
	exit 1
fi

occupant="$(find "${MOUNT_POINT}" -mindepth 1 -maxdepth 1 -print -quit)"
if [ -n "${occupant}" ]; then
	echo "::warning::${MOUNT_POINT} is not empty; mounting over it would hide its content, so no spare disk is mounted"
	exit 0
fi

min_bytes=$((MIN_SIZE_GB * 1024 * 1024 * 1024))
tree="$(lsblk -J -b -o NAME,TYPE,SIZE,RO,FSTYPE,PTTYPE,MOUNTPOINTS)"

if ! jq -e '
	[.. | objects | select(has("name"))]
	| all(
		((.mountpoints | type) == "array")
		and ((.ro | type) == "boolean" or .ro == "0" or .ro == "1")
	)' <<<"${tree}" >/dev/null; then
	echo "::error::lsblk did not report mountpoints and ro for every device; refusing to pick a spare disk" >&2
	exit 1
fi

root_disks="$(jq -c '[
	.blockdevices[]
	| select([.. | objects | .mountpoints[] | select(. == "/")] | length > 0)
	| .name
]' <<<"${tree}")"
if [ "${root_disks}" = "[]" ]; then
	echo "::error::no block device carries / according to lsblk; refusing to pick a spare disk" >&2
	exit 1
fi

disk="$(jq -r --argjson roots "${root_disks}" --argjson min "${min_bytes}" '
	[
		.blockdevices[]
		| select(.type == "disk")
		| select(.name | IN($roots[]) | not)
		| select(.name | test("^(nvme[0-9]+n[0-9]+|sd[a-z]+|vd[a-z]+|xvd[a-z]+)$"))
		| select(.ro == false or .ro == "0")
		| select((.children // []) | length == 0)
		| select((.fstype // "") == "" and (.pttype // "") == "")
		| select([.mountpoints[] | select(. != null)] | length == 0)
		| select((.size | tonumber) >= $min)
	]
	| max_by(.size | tonumber)
	| .name // empty' <<<"${tree}")"

if [ -z "${disk}" ]; then
	echo "::notice::mount_spare_disk.sh mounted no spare disk: No empty, unpartitioned, unmounted disk of at least ${MIN_SIZE_GB}G besides the root disk ${root_disks}"
	exit 0
fi

probe_rc=0
probe="$(sudo blkid -p "/dev/${disk}" 2>&1)" || probe_rc=$?
if [ "${probe_rc}" = 2 ] && [ -n "${probe}" ]; then
	echo "::error::blkid -p /dev/${disk} found nothing but complained: ${probe}" >&2
	exit 1
fi
case "${probe_rc}" in
2) ;;
0)
	echo "::notice::mount_spare_disk.sh mounted no spare disk: /dev/${disk} carries a signature (${probe}), leaving it untouched"
	exit 0
	;;
*)
	echo "::error::blkid -p /dev/${disk} could not tell whether the disk is empty (rc=${probe_rc}): ${probe}" >&2
	exit 1
	;;
esac

signatures="$(sudo wipefs --no-act --noheadings "/dev/${disk}")"
if [ -n "${signatures}" ]; then
	echo "::notice::mount_spare_disk.sh mounted no spare disk: /dev/${disk} carries signatures blkid missed (${signatures}), leaving it untouched"
	exit 0
fi

echo "Formatting the empty spare disk /dev/${disk} and mounting it at ${MOUNT_POINT}"
sudo mkfs.ext4 -q -m 0 -L infinito-spare "/dev/${disk}"
sudo mount "/dev/${disk}" "${MOUNT_POINT}"

source_dev="$(findmnt -n -o SOURCE "${MOUNT_POINT}")"
if [ "${source_dev}" != "/dev/${disk}" ]; then
	echo "::error::${MOUNT_POINT} is backed by '${source_dev}' after mounting /dev/${disk}" >&2
	exit 1
fi

"$DUMP" "after spare-disk mount -> /dev/${disk} at ${MOUNT_POINT}"
