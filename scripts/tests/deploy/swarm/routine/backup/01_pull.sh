#!/usr/bin/env bash
# Runs in-node on the backup host. Prepares ssh trust (private key from
# stdin) and pulls the source host's backups with the real remote-2-local
# pull script, then optionally verifies a marker file arrived.
#
# Arguments:
#   $1 SRC_IP       source host to pull from (backup@SRC_IP)
#   $2 BACKUPS_DIR  backup root on both sides
#   $3 NODE_SRC     repo checkout inside the node
#   $4 VERIFY_REL   optional: dir under BACKUPS_DIR that must hold $5 after
#                   the pull (empty: skip verification)
#   $5 MARKER       marker file name (required when VERIFY_REL is set)
# Stdin: the backup ssh private key.
set -euo pipefail

SRC_IP="${1:?usage: 01_pull.sh SRC_IP BACKUPS_DIR NODE_SRC [VERIFY_REL MARKER]}"
BACKUPS_DIR="${2:?usage: 01_pull.sh SRC_IP BACKUPS_DIR NODE_SRC [VERIFY_REL MARKER]}"
NODE_SRC="${3:?usage: 01_pull.sh SRC_IP BACKUPS_DIR NODE_SRC [VERIFY_REL MARKER]}"
VERIFY_REL="${4:-}"
MARKER="${5:-}"

mkdir -p /root/.ssh
chmod 700 /root/.ssh
cat >/root/.ssh/id_ed25519
chmod 600 /root/.ssh/id_ed25519
printf 'Host *\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n' >/root/.ssh/config
chmod 600 /root/.ssh/config

python3 "${NODE_SRC}/roles/svc-bkp-remote-2-local/files/pull_specific_host.py" \
	"${SRC_IP}" --folder "${BACKUPS_DIR}"

if [ -n "${VERIFY_REL}" ]; then
	: "${MARKER:?MARKER required when VERIFY_REL is set}"
	if [ ! -f "${BACKUPS_DIR}/${VERIFY_REL}/${MARKER}" ]; then
		echo "FAILURE: marker missing after pull (expected under ${BACKUPS_DIR}/${VERIFY_REL})"
		find "${BACKUPS_DIR}" -maxdepth 4 2>/dev/null || true
		exit 1
	fi
	echo "    marker present on backup host after pull"
fi
