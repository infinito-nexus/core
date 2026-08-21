#!/usr/bin/env bash
# Runs in-node on the backup host. Creates the LUKS loop image that
# simulates the plugged-in USB stick and mounts it on the configured
# device mountpoint; the deployed svc-bkp-local-2-device unit then syncs
# onto it like a real plug event.
#
# Loop devices need two things the node container cannot supply itself. It has
# no udev, so LOOP_CTL_GET_FREE hands out a minor whose /dev node never appears
# and cryptsetup aborts with "loop device with autoclear flag is required" —
# hence the mknod loop below. And it cannot load kernel modules, so those nodes
# stay dead unless the host carries the loop driver: `make kernel-loop-load`.
#
# The device-mapper name is host-global too, so a preserved cluster
# (INFINITO_KEEP_SWARM_NODES) leaves it behind and the next round aborts with
# "Device <mapper> already exists" — hence the teardown before luksOpen.
#
# Arguments:
#   $1 USB_IMG      loop image path to create
#   $2 MOUNT_DIR    configured services.local-2-device.mount path
#   $3 DEST_DIR     configured sync destination (<mount><target>); script.py
#                   refuses a missing destination, so an initialized stick
#                   always carries it
#   $4 USB_MAPPER   device-mapper name
#   $5 USB_PASS     LUKS passphrase (drill-only, not a secret)
#   $6 USB_SIZE_MB  loop image size in MiB (default 512); the caller sizes
#                   it from the pulled backup tree so the sync cannot
#                   ENOSPC on app trees larger than a fixed image
set -euo pipefail

USB_IMG="${1:?usage: 02_luks_device.sh USB_IMG MOUNT_DIR DEST_DIR USB_MAPPER USB_PASS [USB_SIZE_MB]}"
MOUNT_DIR="${2:?}"
DEST_DIR="${3:?}"
USB_MAPPER="${4:?}"
USB_PASS="${5:?}"
USB_SIZE_MB="${6:-512}"

for _minor in $(seq 0 7); do
	[ -b "/dev/loop${_minor}" ] || mknod "/dev/loop${_minor}" b 7 "${_minor}"
done

if ! losetup -f >/dev/null 2>&1; then
	echo "FAILURE: no loop device available in this node; the nodes above are dead" >&2
	echo "         without the host-side driver. Run 'make kernel-loop-load' on the host." >&2
	exit 1
fi

losetup -ln 2>/dev/null | awk '/\(deleted\)/ {print $1}' | xargs -r -n1 losetup -d 2>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
losetup -j "${USB_IMG}" 2>/dev/null | cut -d: -f1 | xargs -r -n1 losetup -d 2>/dev/null || true        # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

if cryptsetup status "${USB_MAPPER}" >/dev/null 2>&1; then
	if findmnt -rn -S "/dev/mapper/${USB_MAPPER}" >/dev/null; then
		umount "/dev/mapper/${USB_MAPPER}"
	fi
	cryptsetup luksClose "${USB_MAPPER}"
fi

truncate -s "${USB_SIZE_MB}M" "${USB_IMG}"

probe=""
attempt=0
while [ -z "${probe}" ] && [ "${attempt}" -lt 16 ]; do
	attempt=$((attempt + 1))
	[ "${attempt}" -eq 1 ] || sleep 0.5
	candidate=""
	candidate="$(losetup -f 2>/dev/null)" || candidate=""
	candidate="${candidate%% *}"
	if [ -n "${candidate}" ] && [ ! -b "${candidate}" ]; then
		mknod "${candidate}" b 7 "${candidate#/dev/loop}" 2>/dev/null || candidate=""
	fi
	if attached="$(losetup --find --show "${USB_IMG}" 2>/dev/null)"; then
		probe="${attached}"
	fi
done
if [ -z "${probe}" ]; then
	echo "FAILURE: no loop device is available for ${USB_IMG} after ${attempt} attempts." >&2
	echo "         The rescue artifact carries 'losetup -a' and /dev/loop* for every node." >&2
	exit 1
fi
losetup -d "${probe}"

printf '%s' "${USB_PASS}" | cryptsetup luksFormat --type luks2 --batch-mode "${USB_IMG}" -

printf '%s' "${USB_PASS}" | cryptsetup luksOpen "${USB_IMG}" "${USB_MAPPER}" -

if [ ! -b "/dev/mapper/${USB_MAPPER}" ]; then
	echo "FAILURE: /dev/mapper/${USB_MAPPER} is not a block device after luksOpen." >&2
	echo "         udev claimed the mapping and left a symlink to a /dev/dm-N node this" >&2
	echo "         container's tmpfs /dev never gets. Expected DM_DISABLE_UDEV=1 from the" >&2
	echo "         node container env and a masked systemd-udevd in the node image." >&2
	cryptsetup luksClose "${USB_MAPPER}" 2>/dev/null
	exit 1
fi

mkfs.ext4 -q "/dev/mapper/${USB_MAPPER}"
mkdir -p "${MOUNT_DIR}"
mount "/dev/mapper/${USB_MAPPER}" "${MOUNT_DIR}"
mkdir -p "${DEST_DIR}"
