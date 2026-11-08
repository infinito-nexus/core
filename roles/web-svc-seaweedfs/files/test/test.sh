#!/usr/bin/env bash
# E2E entry point for web-svc-seaweedfs.
# Drives the deployed object store through its published S3 port: the gateway
# refuses unsigned access, the admin identity completes a signed round-trip, a
# consumer identity reaches its own bucket and no other, the anonymous grant
# matches the declared public flag, and the console ports stayed unpublished.
# Variables sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${SEAWEEDFS_TEST_IS_STACK_HOST:?}"
: "${SEAWEEDFS_TEST_LOCAL_URL:?}"
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
