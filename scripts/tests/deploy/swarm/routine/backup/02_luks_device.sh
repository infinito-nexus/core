#!/usr/bin/env bash
# Runs in-node on the backup host. Creates the LUKS loop image that
# simulates the plugged-in USB stick and mounts it on the configured
# device mountpoint; the deployed svc-bkp-local-2-device unit then syncs
# onto it like a real plug event.
#
# Arguments:
#   $1 USB_IMG     loop image path to create
#   $2 MOUNT_DIR   configured services.local-2-device.mount path
#   $3 DEST_DIR    configured sync destination (<mount><target>); script.py
#                  refuses a missing destination, so an initialized stick
#                  always carries it
#   $4 USB_MAPPER  device-mapper name
#   $5 USB_PASS    LUKS passphrase (drill-only, not a secret)
set -euo pipefail

USB_IMG="${1:?usage: 02_luks_device.sh USB_IMG MOUNT_DIR DEST_DIR USB_MAPPER USB_PASS}"
MOUNT_DIR="${2:?}"
DEST_DIR="${3:?}"
USB_MAPPER="${4:?}"
USB_PASS="${5:?}"

fallocate -l 512M "${USB_IMG}" 2>/dev/null || dd if=/dev/zero of="${USB_IMG}" bs=1M count=512 status=none
printf '%s' "${USB_PASS}" | cryptsetup luksFormat --type luks2 --batch-mode "${USB_IMG}" -
printf '%s' "${USB_PASS}" | cryptsetup luksOpen "${USB_IMG}" "${USB_MAPPER}" -
mkfs.ext4 -q "/dev/mapper/${USB_MAPPER}"
mkdir -p "${MOUNT_DIR}"
mount "/dev/mapper/${USB_MAPPER}" "${MOUNT_DIR}"
mkdir -p "${DEST_DIR}"
