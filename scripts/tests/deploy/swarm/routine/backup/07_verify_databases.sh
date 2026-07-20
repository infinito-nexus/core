#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="${1:?role test directory required}"
COMPLETE="${TEST_DIR}/swarm-restore.complete"
MANIFEST="${TEST_DIR}/swarm-restore.manifest"

if [[ ! -f "${COMPLETE}" ]]; then
	echo "FAIL: completed database restore handoff missing at ${COMPLETE}"
	exit 1
fi
# shellcheck disable=SC1091
. "${TEST_DIR}/test.env"
# shellcheck disable=SC1090
. "${COMPLETE}"

if [[ "${BKP_TEST_SWARM_DRILL}" != "true" ]]; then
	echo "FAIL: completed database restore was not produced by the Swarm CI drill"
	exit 1
fi

bash "${TEST_DIR}/db_probe.sh" verify \
	"${PROBE_PRE_TOKEN}" "${PROBE_POST_TOKEN}" "${MANIFEST}"
