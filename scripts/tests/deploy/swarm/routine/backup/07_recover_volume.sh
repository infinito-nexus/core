#!/usr/bin/env bash
# Runs in-node on the manager. Restores the staged volume generation into
# the docker volume with the real volume-2-local recover.py.
#
# Arguments:
#   $1 NODE_SRC     repo checkout inside the node
#   $2 VOL_SRC_DIR  staged generation files dir (…/<volume>/files)
#   $3 VOL_NAME     docker volume to restore into
set -euo pipefail

NODE_SRC="${1:?usage: 07_recover_volume.sh NODE_SRC VOL_SRC_DIR VOL_NAME}"
VOL_SRC_DIR="${2:?}"
VOL_NAME="${3:?}"

PYTHONPATH="${NODE_SRC}" python3 \
	"${NODE_SRC}/roles/svc-bkp-volume-2-local/files/recover.py" \
	"${VOL_SRC_DIR}" "${VOL_NAME}" --no-service-backup
