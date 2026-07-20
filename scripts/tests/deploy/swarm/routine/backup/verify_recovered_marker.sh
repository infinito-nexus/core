#!/usr/bin/env bash
set -euo pipefail

DR_VERIFY_ENV="/tmp/dr-drill-verify-${APP_ID:?APP_ID required (matrix sets it)}.env"
if [ ! -f "${DR_VERIFY_ENV}" ]; then
	echo "SKIP DR verify: the drill recovered nothing for ${APP_ID}"
	exit 0
fi
# shellcheck disable=SC1090
. "${DR_VERIFY_ENV}"

if [ "${DR_NFS_VERIFY:?}" = true ]; then
	if ! docker exec "${NFS_SERVER}" grep -qF "${DR_TOKEN}" "${NFS_VOL_DIR}/${DR_MARKER}" 2>/dev/null; then
		echo "FAILURE: DR-drill marker missing on the live volume after recover + update pass"
		exit 1
	fi
fi

if [ "${DR_DB_VERIFY:?}" = true ]; then
	docker exec "${MGR}" bash "${BKP_IN_NODE}/07_verify_databases.sh" "${ROLE_TEST_DIR}"
fi

echo "==> DR drill PASSED: recovered NFS=${DR_NFS_VERIFY}, databases=${DR_DB_VERIFY}; post-update probes verified"
