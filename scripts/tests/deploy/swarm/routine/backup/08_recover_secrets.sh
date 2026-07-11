#!/usr/bin/env bash
# Runs in-node on the manager. Restores the host secret material from a
# device-recovered snapshot with the real secrets-2-local recover.py and
# verifies the marker came back. The marker is cleared first so the check
# proves the recover restored it, not that it merely survived.
#
# Arguments:
#   $1 NODE_SRC     repo checkout inside the node
#   $2 FILES_DIR    <generation>/files dir of the backup-secrets-to-local snapshot
#   $3 SECRETS_DIR  live secrets dir the snapshot's `secrets` subtree restores into
#   $4 MARKER       marker file that must be restored
set -euo pipefail

NODE_SRC="${1:?usage: 08_recover_secrets.sh NODE_SRC FILES_DIR SECRETS_DIR MARKER}"
FILES_DIR="${2:?usage: 08_recover_secrets.sh NODE_SRC FILES_DIR SECRETS_DIR MARKER}"
SECRETS_DIR="${3:?usage: 08_recover_secrets.sh NODE_SRC FILES_DIR SECRETS_DIR MARKER}"
MARKER="${4:?usage: 08_recover_secrets.sh NODE_SRC FILES_DIR SECRETS_DIR MARKER}"

rm -f "${SECRETS_DIR}/${MARKER}"
if [ -e "${SECRETS_DIR}/${MARKER}" ]; then
	echo "FAILURE: could not clear the secrets marker before recover"
	exit 1
fi

PYTHONPATH="${NODE_SRC}" python3 \
	"${NODE_SRC}/roles/svc-bkp-secrets-2-local/files/recover.py" \
	"${FILES_DIR}" --no-service-backup

if [ ! -f "${SECRETS_DIR}/${MARKER}" ]; then
	echo "FAILURE: secrets marker not restored into ${SECRETS_DIR}"
	exit 1
fi
echo "    secrets restored to ${SECRETS_DIR} via recover.py"
