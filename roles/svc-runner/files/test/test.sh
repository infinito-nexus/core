#!/usr/bin/env bash
# E2E orchestrator for svc-runner.
# Validates env and the runner binary, then delegates to:
#   local.sh    — container health, runner process, DooD
#   external.sh — GitHub registration, smoke dispatch
# Variables sourced from test.env.j2 by test-e2e-cli. RUNNER_API_TOKEN from env only.
set -euo pipefail

: "${DOCKER_IN_CONTAINER:?}"
: "${RUNNER_COUNT:?}"
: "${RUNNER_INSTALL_DIR:?}"
: "${RUNNER_PROJECT_PREFIX:?}"
: "${RUNNER_SRC_DIR:?}"
: "${RUNNER_USER:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${RUNNER_FLAVOR:-}" == "local" ]]; then
    : "${RUNNER_WORKTREE_ROOTS:?}"
    echo "OK: env vars verified (RUNNER_FLAVOR=local, RUNNER_COUNT=${RUNNER_COUNT}, RUNNER_PROJECT_PREFIX=${RUNNER_PROJECT_PREFIX}, RUNNER_WORKTREE_ROOTS=${RUNNER_WORKTREE_ROOTS})"
    echo "SKIP: local flavor registers nowhere, so the runner binary and external.sh do not apply"
    bash "${DIR}/local.sh"
    echo "ALL CHECKS PASSED"
    exit 0
fi

: "${RUNNER_GIT_REF:?}"
: "${RUNNER_GITHUB_OWNER:?}"
: "${RUNNER_GITHUB_REPO:?}"

echo "OK: env vars verified (RUNNER_COUNT=${RUNNER_COUNT}, RUNNER_PROJECT_PREFIX=${RUNNER_PROJECT_PREFIX}, RUNNER_GIT_REF=${RUNNER_GIT_REF})"

if [[ ! -f "${RUNNER_INSTALL_DIR}/1/run.sh" ]]; then
    echo "FAIL: runner binary absent at ${RUNNER_INSTALL_DIR}/1/run.sh"
    exit 1
fi
echo "OK: runner binary present at ${RUNNER_INSTALL_DIR}/1/run.sh"

bash "${DIR}/local.sh"
bash "${DIR}/external.sh"

echo "ALL CHECKS PASSED"
