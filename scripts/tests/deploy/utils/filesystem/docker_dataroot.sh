#!/usr/bin/env bash
# Put the docker data root on a stated filesystem, so CI exercises the code
# paths that depend on it - above all the snapshot mode of
# svc-bkp-volume-2-local, which only engages on btrfs or zfs.
#
# Runs on the machine whose daemon it reconfigures - the runner for compose and
# host mode, each node container for swarm - and restarts that daemon, so it
# must run before anything is pulled or started.
#
# Arguments:
#   $1 FSTYPE    ext4 | btrfs | zfs; empty is a no-op
#   $2 REQUIRED  true when the filesystem was stated: a host that cannot
#                deliver it fails the run. false (default) declines and reports.
#   $3 SIZE      loop image size, e.g. 30G (sparse, so it costs what it holds)
#   $4 IDENTITY  what this machine is called in the zfs pool namespace, which
#                the lab nodes share with the runner. Stated by the caller
#                rather than read from `hostname`, which returns non-zero in the
#                node containers; its `unknown` fallback collapses every node
#                onto one pool name, and they then race for a single pool.
set -euo pipefail

FSTYPE="${1:-}"
REQUIRED="${2:-false}"
SIZE="${3:?SIZE is required - state the loop image size (e.g. 30G) at the call site}"
IDENTITY="${4:?IDENTITY is required - state what this machine is called at the call site}"

MOUNT=/mnt/docker-fs
IMAGE=/var/tmp/docker-fs.img
POOL="infinito_ci_$(printf '%s' "${IDENTITY}" | tr -dc 'A-Za-z0-9_.:-')"
DAEMON=/etc/docker/daemon.json
MISC_MAJOR=10

report() { echo "docker-dataroot-filesystem: $*"; }

current_fstype() {
	stat -f -c %T "${MOUNT}/docker" 2>/dev/null ||
		stat -f -c %T /var/lib/docker 2>/dev/null ||
		stat -f -c %T / 2>/dev/null ||
		echo unknown
}

# Param: $1 status word recorded for this host
# Param: $2 reason behind the status, empty when it needs none
verdict() {
	local status="$1" reason effective
	reason="$(printf '%s' "${2:-}" | tr '\n' ' ')"
	effective="$(current_fstype)"
	report "status=${status} requested=${FSTYPE:-none} effective=${effective}${reason:+ reason=${reason}}"
	[ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
	echo "- \`${IDENTITY}\` docker data root: **${effective}** (requested \`${FSTYPE:-none}\`, ${status})${reason:+ - ${reason}}" \
		>>"${GITHUB_STEP_SUMMARY}"
}

# Param: $1 loop device to detach
# Param: $2 mount point it backs
arm_autoclear() {
	local loop="$1" mount="$2" armed=""
	if ! losetup -d "${loop}"; then
		report "WARNING: ${loop} refused the detach and will leak into the next round"
		return 0
	fi
	if ! mountpoint -q "${mount}"; then
		report "FAIL: detaching ${loop} tore down ${mount}"
		exit 1
	fi
	armed="$(losetup -l -n -O AUTOCLEAR "${loop}" 2>/dev/null | tr -d '[:space:]')"
	[ "${armed}" = 1 ] ||
		report "WARNING: ${loop} did not arm autoclear (AUTOCLEAR='${armed}')"
}

# Make /dev/zfs usable, reporting 1 when the module is not loaded at all.
#
# A node container's /dev is populated once at creation, and udevd is masked, so
# a module loaded afterwards leaves no device node behind. /dev/zfs is a misc
# device, which means it appears in /proc/misc and never in /proc/devices.
zfs_device_ready() {
	local minor
	[ ! -c /dev/zfs ] || return 0
	minor="$(awk '$2 == "zfs" {print $1}' /proc/misc)"
	[ -n "${minor}" ] || return 1
	report "the module is loaded but this /dev predates it; creating the node from /proc/misc"
	mknod /dev/zfs c "${MISC_MAJOR}" "${minor}"
}

# Param: $1 pool whose leftovers from an earlier bring-up have to go
#
# Pools live in the kernel, which the lab nodes share with the runner and with
# every later distro of the same sweep, while the container teardown only removes
# containers. A pool of this name is therefore still imported when the next
# iteration starts, and `zpool create` refuses the name rather than reusing it.
# Its vdev is a loop device backed by an image the dead container already
# unlinked, so that space stays claimed until the loop is detached as well.
#
# A pool that refuses the destroy is by definition not a leftover: something
# still holds it. That case declines through the usual contract instead of
# ending the run, so a reclaim can never be more destructive than the state it
# was written to clean up.
reclaim_stale_pool() {
	local pool="$1" vdev destroy_out
	zpool list -H -o name "${pool}" >/dev/null 2>&1 || return 0
	vdev="$(zpool list -vHP "${pool}" | awk 'NR == 2 {print $1}')"
	report "destroying ${pool}, left imported on this kernel by an earlier bring-up"
	if ! destroy_out="$(zpool destroy -f "${pool}" 2>&1)"; then
		decline "${pool} is held elsewhere and is therefore not stale: ${destroy_out}"
	fi
	if [ -b "${vdev}" ]; then
		losetup -d "${vdev}"
		report "detached its vdev ${vdev}"
	else
		report "WARNING: its vdev '${vdev}' is no block device; that loop stays attached"
	fi
}

# Param: $1 filesystem the caller asked for
#
# stat reports ext4 as ext2/ext3, so the requested name and the reported one are
# compared through this table rather than directly.
prepared_matches() {
	case "$1:$(current_fstype)" in
	ext4:ext2/ext3 | btrfs:btrfs | zfs:zfs) return 0 ;;
	*) return 1 ;;
	esac
}

# Give the prepared data root up so a different filesystem can take its place.
#
# The pick is drawn per distro iteration, so on a host that survives the sweep -
# the runner in compose and host mode - the second distro usually asks for
# something else. Docker has to stop before its data root can be dismantled, and
# the loop device only releases the backing image once the mount above it is
# gone. Everything docker cached on the old root goes with it; that is the price
# of covering more than one filesystem per entry.
release_prepared() {
	local loop
	report "replacing the prepared $(current_fstype) data root with ${FSTYPE}"
	systemctl stop docker.socket 2>/dev/null || true # nocheck: shell-or-true -- the socket unit is absent on distros that ship docker without it
	systemctl stop docker 2>/dev/null || true        # nocheck: shell-or-true -- docker is not running yet on a runner that never started it
	DOCKER_STOPPED=true
	if zpool list -H -o name "${POOL}" >/dev/null 2>&1; then
		reclaim_stale_pool "${POOL}"
	else
		umount "${MOUNT}"
	fi
	loop="$(losetup -j "${IMAGE}" -O NAME -n | head -n1)"
	if [ -n "${loop}" ] && [ -b "${loop}" ]; then
		losetup -d "${loop}"
	fi
	rm -f "${IMAGE}"
}

decline() {
	if [ "${REQUIRED}" = true ]; then
		report "FAIL: ${FSTYPE} was stated but cannot be delivered: $*"
		verdict required-but-unavailable "$*"
		exit 1
	fi
	report "skipping ${FSTYPE}: $*"
	verdict declined "$*"
	exit 0
}

case "${FSTYPE}" in
ext4 | btrfs | zfs) ;;
"")
	report "no filesystem stated, leaving the data root where it is"
	verdict unchanged
	exit 0
	;;
*)
	report "FAIL: unknown filesystem '${FSTYPE}'"
	verdict unknown-filesystem
	exit 1
	;;
esac

[ "$(id -u)" -eq 0 ] || decline "not running as root"

install_packages() {
	if command -v apt-get >/dev/null; then
		APT_TIMEOUT=10m
		APT_INSTALL_TIMEOUT=20m
		APT_OPTS=(-o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
		DEBIAN_FRONTEND=noninteractive timeout -k 30 "${APT_TIMEOUT}" apt-get "${APT_OPTS[@]}" update -qq
		DEBIAN_FRONTEND=noninteractive timeout -k 30 "${APT_INSTALL_TIMEOUT}" apt-get "${APT_OPTS[@]}" install -y --no-install-recommends "$@"
	elif command -v pacman >/dev/null; then
		pacman -Sy --noconfirm --needed "$@"
	elif command -v dnf >/dev/null; then
		if dnf -y install "$@"; then
			return 0
		fi
		dnf -y install epel-release || return 1
		dnf -y install "$@"
	else
		return 1
	fi
}

require_tool() {
	local tool="$1" candidate
	shift
	command -v "${tool}" >/dev/null && return 0
	for candidate in "$@"; do
		report "installing ${candidate} for ${tool}"
		install_packages "${candidate}" >/dev/null 2>&1 || continue
		command -v "${tool}" >/dev/null && return 0
	done
	return 1
}

require_tool losetup util-linux || decline "losetup is unavailable"
require_tool mountpoint util-linux || decline "mountpoint is unavailable"

case "${FSTYPE}" in
ext4)
	require_tool mkfs.ext4 e2fsprogs || decline "mkfs.ext4 is unavailable"
	;;
btrfs)
	require_tool mkfs.btrfs btrfs-progs || decline "btrfs-progs is unavailable"
	;;
zfs)
	require_tool zpool zfsutils-linux zfs zfs-utils ||
		decline "the zfs userland is unavailable on this distribution"
	if ! modprobe_out="$(modprobe zfs 2>&1)"; then
		report "modprobe zfs failed: ${modprobe_out}"
	fi
	if [ ! -c /dev/zfs ] && zfs_major="$(awk '$2 == "zfs" {print $1}' /proc/devices | head -n1)" && [ -n "${zfs_major}" ]; then
		mknod /dev/zfs c "${zfs_major}" 0
	fi
	zfs_device_ready ||
		decline "the zfs kernel module is not loaded on the host: ${modprobe_out}"
	;;
esac

restore_docker() {
	[ "${DOCKER_STOPPED:-false}" = true ] || return 0
	systemctl cat docker.service >/dev/null 2>&1 || return 0
	systemctl start docker ||
		report "WARNING: docker did not come back up after the ${FSTYPE} setup"
}

trap restore_docker EXIT

if mountpoint -q "${MOUNT}"; then
	if prepared_matches "${FSTYPE}"; then
		if [ "${FSTYPE}" = zfs ] && zpool list -H -o name "${POOL}" >/dev/null 2>&1; then
			zfs set acltype=posixacl xattr=sa "${POOL}"
		fi
		report "${MOUNT} already carries ${FSTYPE}"
		verdict already-prepared
		exit 0
	fi
	release_prepared
fi

if command -v zpool >/dev/null 2>&1 && zfs_device_ready; then
	reclaim_stale_pool "${POOL}"
fi

report "putting the docker data root on ${FSTYPE}"
systemctl stop docker.socket 2>/dev/null || true # nocheck: shell-or-true -- the socket unit is absent on distros that ship docker without it
systemctl stop docker 2>/dev/null || true        # nocheck: shell-or-true -- docker is not running yet on a runner that never started it
DOCKER_STOPPED=true

mkdir -p "${MOUNT}" "$(dirname "${IMAGE}")"
rm -f "${IMAGE}"
truncate -s "${SIZE}" "${IMAGE}"
LOOP=""
attempt=0
while [ -z "${LOOP}" ] && [ "${attempt}" -lt 16 ]; do
	attempt=$((attempt + 1))
	[ "${attempt}" -eq 1 ] || sleep 0.5
	candidate=""
	candidate="$(losetup -f 2>/dev/null)" || candidate=""
	candidate="${candidate%% *}"
	if [ -n "${candidate}" ] && [ ! -b "${candidate}" ]; then
		mknod "${candidate}" b 7 "${candidate#/dev/loop}" 2>/dev/null || candidate=""
	fi
	if attached="$(losetup --find --show "${IMAGE}" 2>/dev/null)"; then
		LOOP="${attached}"
	fi
done
[ -n "${LOOP}" ] || decline "no loop device could be claimed after ${attempt} attempts"

if [ "${FSTYPE}" = zfs ]; then
	if ! zpool_out="$(zpool create -f -m "${MOUNT}" -O acltype=posixacl -O xattr=sa "${POOL}" "${LOOP}" 2>&1)"; then
		losetup -d "${LOOP}" ||
			report "WARNING: ${LOOP} refused the detach and will leak into the next round"
		rm -f "${IMAGE}"
		decline "zpool create failed: ${zpool_out}"
	fi
	zfs create -o mountpoint="${MOUNT}/docker" "${POOL}/docker"
else
	"mkfs.${FSTYPE}" -q "${LOOP}"
	mount -t "${FSTYPE}" "${LOOP}" "${MOUNT}"
	arm_autoclear "${LOOP}" "${MOUNT}"
	if [ "${FSTYPE}" = btrfs ]; then
		btrfs subvolume create "${MOUNT}/docker" >/dev/null
	else
		mkdir -p "${MOUNT}/docker"
	fi
fi

mkdir -p "$(dirname "${DAEMON}")"
python3 - "${DAEMON}" "${MOUNT}/docker" <<'PYTHON'
import json
import pathlib
import sys

path, root = pathlib.Path(sys.argv[1]), sys.argv[2]
config = json.loads(path.read_text()) if path.is_file() and path.read_text().strip() else {}
config["data-root"] = root
path.write_text(json.dumps(config, indent=2) + "\n")
PYTHON

if systemctl cat docker.service >/dev/null 2>&1; then
	systemctl start docker
	DOCKER_STOPPED=false
	verdict applied
else
	report "docker.service is not installed yet; the data root takes effect when it is"
	verdict applied-pending-docker
fi
