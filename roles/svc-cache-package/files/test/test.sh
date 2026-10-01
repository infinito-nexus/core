#!/usr/bin/env bash
# E2E orchestrator for svc-cache-package.
# Drives the deployed cache: Nexus answers, every declared repository exists
# in it, the frontend holds a leaf cert for every host it terminates TLS for,
# and a request carrying a real upstream Host header comes back proxied onto
# the matching repository. Every check interrogates the running stack.
# Variables sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${CACHE_PACKAGE_TEST_CONTAINER:?}"
: "${CACHE_PACKAGE_TEST_FRONTEND:?}"
: "${CACHE_PACKAGE_TEST_PORT:?}"
: "${CACHE_PACKAGE_TEST_CERTS_DIR:?}"
: "${CACHE_PACKAGE_TEST_REPOS:?}"
: "${CACHE_PACKAGE_TEST_HOSTS:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "${DIR}/probe.py"
