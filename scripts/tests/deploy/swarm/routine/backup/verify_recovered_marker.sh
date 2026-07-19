#!/usr/bin/env bash
# Runs on the controller after the matrix update pass. Asserts the DR-drill
# marker (seeded pre-backup) survived recovery plus the update-pass bring-up
# onto the recovered NFS export. Skips when the sentinel is absent (the drill
# recovered nothing: the app declares no NFS-flagged volume).
set -euo pipefail

DR_VERIFY_ENV="/tmp/dr-drill-verify-${APP_ID:?APP_ID required (matrix sets it)}.env"
if [ ! -f "${DR_VERIFY_ENV}" ]; then
	echo "SKIP DR verify: the drill recovered nothing for ${APP_ID}"
	exit 0
fi
# shellcheck disable=SC1090
. "${DR_VERIFY_ENV}"

if ! docker exec "${NFS_SERVER}" grep -qF "${DR_TOKEN}" "${NFS_VOL_DIR}/${DR_MARKER}" 2>/dev/null; then
	echo "FAILURE: DR-drill marker missing on the live volume after recover + update pass"
	exit 1
fi
echo "==> DR drill PASSED: backup -> teardown -> recover device->nfs->volume->secrets -> live marker verified after the update pass"
