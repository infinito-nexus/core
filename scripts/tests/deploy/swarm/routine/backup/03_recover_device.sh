#!/usr/bin/env bash
# Runs in-node on the backup host. Closes the mounted drill device, then
# recovers the newest snapshot from the LUKS image into a local restore
# root with the real local-2-device recover.py (full luksOpen path) and
# verifies the marker came back.
#
# Arguments:
#   $1 NODE_SRC      repo checkout inside the node
#   $2 USB_IMG       LUKS loop image
#   $3 USB_MOUNT     mountpoint recover.py may use
#   $4 RESTORE_ROOT  target dir for the recovered snapshot
#   $5 USB_MAPPER    device-mapper name to close before recovering
#   $6 SRC_REL       dir under RESTORE_ROOT that must hold $7 afterwards
#   $7 MARKER        marker file name
#   $8 USB_PASS      LUKS passphrase (drill-only, not a secret)
set -euo pipefail

NODE_SRC="${1:?usage: 03_recover_device.sh NODE_SRC USB_IMG USB_MOUNT RESTORE_ROOT USB_MAPPER SRC_REL MARKER USB_PASS}"
USB_IMG="${2:?}"
USB_MOUNT="${3:?}"
RESTORE_ROOT="${4:?}"
USB_MAPPER="${5:?}"
SRC_REL="${6:?}"
MARKER="${7:?}"
USB_PASS="${8:?}"

umount "${USB_MOUNT}" 2>/dev/null || true
cryptsetup luksClose "${USB_MAPPER}" 2>/dev/null || true
rm -rf "${RESTORE_ROOT}"
mkdir -p "${RESTORE_ROOT}"

printf '%s' "${USB_PASS}" | PYTHONPATH="${NODE_SRC}" python3 \
	"${NODE_SRC}/roles/svc-bkp-local-2-device/files/recover.py" \
	"${USB_IMG}" "${USB_MOUNT}" "${RESTORE_ROOT}" --passphrase-stdin

if [ ! -f "${RESTORE_ROOT}/${SRC_REL}/${MARKER}" ]; then
	echo "FAILURE: marker missing after device recover (expected under ${RESTORE_ROOT}/${SRC_REL})"
	find "${RESTORE_ROOT}" -maxdepth 4 2>/dev/null || true
	exit 1
fi
echo "    marker recovered from device into ${RESTORE_ROOT}"
