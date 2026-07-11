#!/usr/bin/env bash
# Runs in-node on the NFS server. Restores the staged device-recovered
# files into the live export with the real nfs-2-local recover.py and
# verifies the marker is back.
#
# Arguments:
#   $1 NODE_SRC     repo checkout inside the node
#   $2 STAGE_DIR    staging dir holding the recovered generation
#   $3 NFS_VOL_DIR  live export dir to restore into
#   $4 MARKER       marker file that must exist afterwards
set -euo pipefail

NODE_SRC="${1:?usage: 06_recover_nfs.sh NODE_SRC STAGE_DIR NFS_VOL_DIR MARKER}"
STAGE_DIR="${2:?}"
NFS_VOL_DIR="${3:?}"
MARKER="${4:?}"

PYTHONPATH="${NODE_SRC}" python3 \
	"${NODE_SRC}/roles/svc-bkp-nfs-2-local/files/recover.py" \
	"${STAGE_DIR}" "${NFS_VOL_DIR}" --no-service-backup

if [ ! -e "${NFS_VOL_DIR}/${MARKER}" ]; then
	echo "FAILURE: marker not written back to the NFS export during recover"
	exit 1
fi
echo "    device-recovered files restored to the live NFS export via recover.py"
