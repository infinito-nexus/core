#!/bin/bash
# Stores a hard-linked differential snapshot of the host's generated
# secret material (infinito secrets + tokens, the self-signed CA, the
# Let's Encrypt account + certs, the ACME DNS credentials) and the node
# identity in the local backup directory. None of this lives in a docker
# volume, the NFS export or the operator inventory, so without this
# snapshot a restored host cannot re-serve its running tokens and TLS
# trust. The node subtree keeps ssh host keys + machine-id (universal
# FHS paths, not configurable): a fresh host restore needs them for its
# ssh identity and, via machine-id, a stable backup addressing hash.
#
# Arguments:
#   $1 BACKUPS_DIR  local backup root
#   $2 REPO_NAME    repository directory name inside the machine hash dir
#   $3.. NAME=DIR   named source directories; a missing optional dir is
#                   skipped (CA absent in letsencrypt mode, ACME absent
#                   in self-signed mode).
set -euo pipefail

BACKUPS_DIR="${1:?usage: script.sh BACKUPS_DIR REPO_NAME NAME=DIR...}"
REPO_NAME="${2:?usage: script.sh BACKUPS_DIR REPO_NAME NAME=DIR...}"
shift 2

MACHINE_HASH="$(sha256sum /etc/machine-id | cut -c1-64)"
REPO_DIR="${BACKUPS_DIR%/}/${MACHINE_HASH}/${REPO_NAME}"
GENERATION="$(date +%Y%m%d%H%M%S)"
DEST_DIR="${REPO_DIR}/${GENERATION}/files"

PREVIOUS_FILES=""
if [[ -d "${REPO_DIR}" ]]; then
	PREVIOUS_GENERATION="$(find "${REPO_DIR}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n1)"
	if [[ -n "${PREVIOUS_GENERATION}" && -d "${PREVIOUS_GENERATION}/files" ]]; then
		PREVIOUS_FILES="${PREVIOUS_GENERATION}/files"
	fi
fi

cleanup_failed_generation() {
	rm -rf "${REPO_DIR:?}/${GENERATION:?}"
}
trap cleanup_failed_generation ERR

mkdir -p "${DEST_DIR}"

snapshot_subtree() {
	local name="$1" src="$2"
	local dest="${DEST_DIR}/${name}"
	mkdir -p "${dest}"
	local args=(-a)
	if [[ -n "${PREVIOUS_FILES}" && -d "${PREVIOUS_FILES}/${name}" ]]; then
		args+=(--link-dest "${PREVIOUS_FILES}/${name}/")
	fi
	rsync "${args[@]}" "${src}" "${dest}/"
}

for spec in "$@"; do
	name="${spec%%=*}"
	src="${spec#*=}"
	if [[ ! -e "${src}" ]]; then
		echo "SKIP: ${name} source ${src} absent"
		continue
	fi
	snapshot_subtree "${name}" "${src%/}/"
	echo "OK: ${name} snapshot from ${src}"
done

mkdir -p "${DEST_DIR}/node"
cp -a /etc/machine-id "${DEST_DIR}/node/machine-id"
for key in /etc/ssh/ssh_host_*; do
	[[ -e "${key}" ]] || continue
	cp -a "${key}" "${DEST_DIR}/node/"
done
echo "OK: node identity snapshot (ssh host keys + machine-id)"

echo "OK: differential secrets backup stored in ${DEST_DIR}"
