#!/usr/bin/env bash
# E2E entry point for web-svc-seaweedfs.
# Variables sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${SEAWEEDFS_TEST_CONTAINER:?}"
: "${SEAWEEDFS_TEST_IS_STACK_HOST:?}"
: "${SEAWEEDFS_TEST_BIND_HOST:?}"
if [ -n "${SEAWEEDFS_TEST_SWARM_SERVICE:-}" ]; then
	: "${SEAWEEDFS_TEST_LOOPBACK_URL:?}"
else
	: "${SEAWEEDFS_TEST_LOCAL_URL:?}"
fi
: "${SEAWEEDFS_TEST_REGION:?}"
: "${SEAWEEDFS_TEST_FILER_PORT:?}"
: "${SEAWEEDFS_TEST_MASTER_PORT:?}"
: "${SEAWEEDFS_TEST_ADMIN_ACCESS_KEY_B64:?}"
: "${SEAWEEDFS_TEST_ADMIN_SECRET_KEY_B64:?}"
: "${SEAWEEDFS_TEST_PRIMARY_IS_PUBLIC:?}"

if [ "${SEAWEEDFS_TEST_IS_STACK_HOST}" != "true" ]; then
	echo "SKIP: not the stack host for the SeaweedFS engine"
	exit 0
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "${DIR}/probe.py"
