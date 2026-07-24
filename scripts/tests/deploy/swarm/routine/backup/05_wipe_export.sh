#!/usr/bin/env bash
# Runs in-node on the NFS server. Wipes the live export volume dir, proves
# the marker is gone, and prepares the empty staging dir for the restore.
#
# Arguments:
#   $1 NFS_VOL_DIR  live export dir of the app volume
#   $2 MARKER       marker file that must be gone after the wipe
#   $3 STAGE_DIR    staging dir to (re)create for the incoming restore
set -euo pipefail

NFS_VOL_DIR="${1:?usage: 05_wipe_export.sh NFS_VOL_DIR MARKER STAGE_DIR}"
MARKER="${2:?usage: 05_wipe_export.sh NFS_VOL_DIR MARKER STAGE_DIR}"
STAGE_DIR="${3:?usage: 05_wipe_export.sh NFS_VOL_DIR MARKER STAGE_DIR}"

rm -rf "${NFS_VOL_DIR:?}"/* "${NFS_VOL_DIR}"/.[!.]* 2>/dev/null || true
if [ -e "${NFS_VOL_DIR}/${MARKER}" ]; then
	echo "FAILURE: marker still present after wiping the live NFS volume"
	exit 1
fi
echo "    live NFS volume wiped (marker gone)"

rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"
