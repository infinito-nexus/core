#!/usr/bin/env bash
set -euo pipefail

: "${SEMAPHORE_TEST_EGRESS_SERVICE:?}"
: "${SEMAPHORE_TEST_IS_STACK_HOST:?}"
: "${SEMAPHORE_TEST_JOURNAL_SINCE?}"
: "${SEMAPHORE_TEST_LOG_TAG:?}"
: "${SEMAPHORE_TEST_REFUSED_TARGET:?}"
: "${SEMAPHORE_TEST_WORKSPACES_SKIP?}"

if [ "${SEMAPHORE_TEST_IS_STACK_HOST}" != "true" ]; then
	echo "SKIP: not the stack host, which runs the workspace runners"
	exit 0
fi
if [ -n "${SEMAPHORE_TEST_WORKSPACES_SKIP}" ]; then
	echo "SKIP: ${SEMAPHORE_TEST_WORKSPACES_SKIP}"
	exit 0
fi
if [ -z "${SEMAPHORE_TEST_JOURNAL_SINCE}" ]; then
	echo "SKIP: this run deployed no web-app-semaphore on the stack host, so its egress spec did not run"
	exit 0
fi

probe="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/egress_log.py"

journalctl --since "@${SEMAPHORE_TEST_JOURNAL_SINCE}" --no-pager --output=json --output-fields=MESSAGE,CONTAINER_NAME \
	"SYSLOG_IDENTIFIER=${SEMAPHORE_TEST_LOG_TAG}" |
	python3 -I "${probe}" "${SEMAPHORE_TEST_EGRESS_SERVICE}" "${SEMAPHORE_TEST_REFUSED_TARGET}"
