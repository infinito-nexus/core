#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="${1:?role test directory required}"
BACKUPS_ROOT="${2:?backup root required}"
PENDING="${TEST_DIR}/swarm-restore.pending"
COMPLETE="${TEST_DIR}/swarm-restore.complete"
MANIFEST="${TEST_DIR}/swarm-restore.manifest"

if [[ ! -f "${PENDING}" ]]; then
	echo "FAIL: database restore handoff missing at ${PENDING}"
	exit 1
fi
# shellcheck disable=SC1091
. "${TEST_DIR}/test.env"
# shellcheck disable=SC1090
. "${PENDING}"

if [[ "${BKP_TEST_SWARM_DRILL}" != "true" ]]; then
	echo "FAIL: database restore handoff was not created by the Swarm CI drill"
	exit 1
fi

BKP_TEST_BACKUPS_DIR="${BACKUPS_ROOT%/}"
REPO_DIR="${BKP_TEST_BACKUPS_DIR}/${MACHINE_HASH}/${REPO_NAME}"
BKP_TEST_RESTORED_DATABASES_FILE="${MANIFEST}"
export BKP_TEST_BACKUPS_DIR REPO_DIR BKP_TEST_RESTORED_DATABASES_FILE
export MACHINE_HASH REPO_NAME NEWEST_GENERATION

if [[ ! -d "${REPO_DIR}/${NEWEST_GENERATION}" ]]; then
	echo "FAIL: handed-off database backup generation missing at ${REPO_DIR}/${NEWEST_GENERATION}"
	exit 1
fi

bash "${TEST_DIR}/db_restore.sh"
if [[ ! -s "${MANIFEST}" ]]; then
	echo "FAIL: database restore completed without a restored-database manifest"
	exit 1
fi
mv "${PENDING}" "${COMPLETE}"
echo "OK: consumed Swarm database restore handoff"
