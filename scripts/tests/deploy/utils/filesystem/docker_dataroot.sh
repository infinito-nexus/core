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
#   $3 SIZE      loop image size, default 30G (sparse, so it costs what it holds)
set -euo pipefail

FSTYPE="${1:-}"
REQUIRED="${2:-false}"
SIZE="${3:-30G}"

MOUNT=/mnt/docker-fs
IMAGE=/var/tmp/docker-fs.img
POOL_HOST="$(hostname 2>/dev/null || echo unknown)"
POOL="infinito_ci_$(printf '%s' "${POOL_HOST}" | tr -dc 'A-Za-z0-9_.:-')"
DAEMON=/etc/docker/daemon.json

report() { echo "docker-dataroot-filesystem: $*"; }

current_fstype() {
	stat -f -c %T "${MOUNT}/docker" 2>/dev/null ||
		stat -f -c %T /var/lib/docker 2>/dev/null ||
		stat -f -c %T / 2>/dev/null ||
		echo unknown
}

verdict() {
	local status="$1" effective host
	effective="$(current_fstype)"
	host="$(hostname 2>/dev/null || echo unknown)"
	report "status=${status} requested=${FSTYPE:-none} effective=${effective}"
	[ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
	echo "- \`${host}\` docker data root: **${effective}** (requested \`${FSTYPE:-none}\`, ${status})" \
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

decline() {
	if [ "${REQUIRED}" = true ]; then
		report "FAIL: ${FSTYPE} was stated but cannot be delivered: $*"
		verdict required-but-unavailable
		exit 1
	fi
	report "skipping ${FSTYPE}: $*"
	verdict declined
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
		DEBIAN_FRONTEND=noninteractive apt-get update -qq
		DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
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
	modprobe zfs 2>/dev/null || true
	if [ ! -c /dev/zfs ]; then
		zfs_major="$(awk '$2 == "zfs" {print $1}' /proc/devices | head -n1)"
		[ -n "${zfs_major}" ] && mknod /dev/zfs c "${zfs_major}" 0
	fi
	[ -c /dev/zfs ] || decline "the zfs kernel module is not loaded on the host"
	;;
esac

if mountpoint -q "${MOUNT}"; then
	if [ "${FSTYPE}" = zfs ] && zpool list -H -o name "${POOL}" >/dev/null 2>&1; then
		zfs set acltype=posixacl xattr=sa "${POOL}"
	fi
	report "${MOUNT} is already prepared"
	verdict already-prepared
	exit 0
fi

report "putting the docker data root on ${FSTYPE}"
systemctl stop docker.socket 2>/dev/null || true
systemctl stop docker 2>/dev/null || true

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
	zpool create -f -m "${MOUNT}" -O acltype=posixacl -O xattr=sa "${POOL}" "${LOOP}"
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
	verdict applied
else
	report "docker.service is not installed yet; the data root takes effect when it is"
	verdict applied-pending-docker
fi
