#!/usr/bin/env bash
# Runs in-node on the backup host. Creates a LUKS loop image as the
# simulated USB stick, mounts it and mirrors the local backups onto it
# with the real local-2-device script, then verifies the marker arrived.
#
# Arguments:
#   $1 NODE_SRC     repo checkout inside the node
#   $2 BACKUPS_DIR  local backup root to mirror
#   $3 USB_IMG      loop image path to create
#   $4 USB_MOUNT    mountpoint for the opened device
#   $5 USB_MAPPER   device-mapper name
#   $6 USB_PASS     LUKS passphrase (drill-only, not a secret)
#   $7 MARKER       marker file that must exist on the device afterwards
set -euo pipefail

NODE_SRC="${1:?usage: 02_mirror_to_device.sh NODE_SRC BACKUPS_DIR USB_IMG USB_MOUNT USB_MAPPER USB_PASS MARKER}"
BACKUPS_DIR="${2:?}"
USB_IMG="${3:?}"
USB_MOUNT="${4:?}"
USB_MAPPER="${5:?}"
USB_PASS="${6:?}"
MARKER="${7:?}"

fallocate -l 512M "${USB_IMG}" 2>/dev/null || dd if=/dev/zero of="${USB_IMG}" bs=1M count=512 status=none
printf '%s' "${USB_PASS}" | cryptsetup luksFormat --type luks2 --batch-mode "${USB_IMG}" -
printf '%s' "${USB_PASS}" | cryptsetup luksOpen "${USB_IMG}" "${USB_MAPPER}" -
mkfs.ext4 -q "/dev/mapper/${USB_MAPPER}"
mkdir -p "${USB_MOUNT}"
mount "/dev/mapper/${USB_MAPPER}" "${USB_MOUNT}"

python3 "${NODE_SRC}/roles/svc-bkp-local-2-device/files/script.py" \
	"${BACKUPS_DIR}" "${USB_MOUNT}"

if ! find "${USB_MOUNT}" -name "${MARKER}" 2>/dev/null | grep -q .; then
	echo "FAILURE: marker missing on the encrypted USB after local-2-device sync"
	exit 1
fi
echo "    marker present on encrypted USB"
