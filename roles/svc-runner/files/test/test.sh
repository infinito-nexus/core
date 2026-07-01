#!/usr/bin/env bash
# E2E orchestrator for svc-runner.
# Validates env and the runner binary, then delegates to:
#   local.sh    — container health, runner process, DooD
#   external.sh — GitHub registration, smoke dispatch
# Variables sourced from test.env.j2 by test-e2e-cli. RUNNER_API_TOKEN from env only.
set -euo pipefail

: "${DOCKER_IN_CONTAINER:?}"
: "${RUNNER_COUNT:?}"
: "${RUNNER_GIT_REF:?}"
: "${RUNNER_GITHUB_OWNER:?}"
: "${RUNNER_GITHUB_REPO:?}"
: "${RUNNER_INSTALL_DIR:?}"
: "${RUNNER_PROJECT_PREFIX:?}"
: "${RUNNER_USER:?}"

echo "OK: env vars verified (RUNNER_COUNT=${RUNNER_COUNT}, RUNNER_PROJECT_PREFIX=${RUNNER_PROJECT_PREFIX}, RUNNER_GIT_REF=${RUNNER_GIT_REF})"

if [[ ! -f "${RUNNER_INSTALL_DIR}/1/run.sh" ]]; then
    echo "FAIL: runner binary absent at ${RUNNER_INSTALL_DIR}/1/run.sh"
    exit 1
fi
echo "OK: runner binary present at ${RUNNER_INSTALL_DIR}/1/run.sh"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${DIR}/local.sh"
bash "${DIR}/external.sh"

echo "ALL CHECKS PASSED"
