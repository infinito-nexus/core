#!/bin/bash
# Stores a hard-linked differential snapshot of the NFS export in the
# local backup directory.
#
# Arguments:
#   $1 SOURCE_DIR   NFS export base to back up
#   $2 BACKUPS_DIR  local backup root
#   $3 REPO_NAME    repository directory name inside the machine hash dir
#   $4 EXCLUDE_REL  optional path relative to SOURCE_DIR to exclude
#                   (the shared backup root inside the export; without it
#                   every generation snapshots all previous backups)
#
# Environment:
#   BKP_NFS_2_LOCAL_GENERATION  optional generation name override
#                               (defaults to the current timestamp)
set -euo pipefail

SOURCE_DIR="${1:?usage: script.sh SOURCE_DIR BACKUPS_DIR REPO_NAME [EXCLUDE_REL]}"
BACKUPS_DIR="${2:?usage: script.sh SOURCE_DIR BACKUPS_DIR REPO_NAME [EXCLUDE_REL]}"
REPO_NAME="${3:?usage: script.sh SOURCE_DIR BACKUPS_DIR REPO_NAME [EXCLUDE_REL]}"
EXCLUDE_REL="${4:-}"

if [[ ! -d "${SOURCE_DIR}" ]]; then
    echo "ERROR: ${SOURCE_DIR} missing; this host is expected to serve the NFS export" >&2
    exit 1
fi

MACHINE_HASH="$(sha256sum /etc/machine-id | cut -c1-64)"
REPO_DIR="${BACKUPS_DIR%/}/${MACHINE_HASH}/${REPO_NAME}"
GENERATION="${BKP_NFS_2_LOCAL_GENERATION:-$(date +%Y%m%d%H%M%S)}"
DEST_DIR="${REPO_DIR}/${GENERATION}/files"

PREVIOUS_FILES=""
if [[ -d "${REPO_DIR}" ]]; then
    PREVIOUS_GENERATION="$(find "${REPO_DIR}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n1)"
    if [[ -n "${PREVIOUS_GENERATION}" && -d "${PREVIOUS_GENERATION}/files" ]]; then
        PREVIOUS_FILES="${PREVIOUS_GENERATION}/files/"
    fi
fi

cleanup_failed_generation() {
    rm -rf "${REPO_DIR:?}/${GENERATION:?}"
}
trap cleanup_failed_generation ERR

mkdir -p "${DEST_DIR}"

rsync_args=(-a --numeric-ids --delete)
if [[ -n "${EXCLUDE_REL}" ]]; then
    rsync_args+=(--exclude "/${EXCLUDE_REL#/}")
fi
if [[ -n "${PREVIOUS_FILES}" ]]; then
    rsync_args+=(--link-dest "${PREVIOUS_FILES}")
fi

rc=0
rsync "${rsync_args[@]}" "${SOURCE_DIR%/}/" "${DEST_DIR}/" || rc=$?
if [[ "${rc}" -eq 24 ]]; then
    echo "WARN: rsync exit 24 (files vanished from the live export mid-transfer), snapshot kept"
elif [[ "${rc}" -ne 0 ]]; then
    cleanup_failed_generation
    echo "ERROR: rsync failed with exit ${rc}, incomplete generation removed" >&2
    exit "${rc}"
fi
echo "OK: differential backup of ${SOURCE_DIR} stored in ${DEST_DIR}"
