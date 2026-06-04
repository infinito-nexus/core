#!/usr/bin/env bash
# Verifies svc-runner by deploying a real app inside the runner's own Docker
# volume and project namespace. Variables are sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${RUNNER_INSTALL_DIR:?}"
: "${RUNNER_USER:?}"
: "${DOCKER_IN_CONTAINER:?}"

# Skip gracefully when svc-runner was never deployed on this host
if ! id "${RUNNER_USER}" >/dev/null 2>&1; then
    echo "SKIP: ${RUNNER_USER} user absent — svc-runner not deployed on this host"
    exit 0
fi

# Verify the runner binary was extracted
if [[ ! -f "${RUNNER_INSTALL_DIR}/1/run.sh" ]]; then
    echo "FAIL: runner binary not found at ${RUNNER_INSTALL_DIR}/1/run.sh"
    exit 1
fi
echo "OK: runner binary present at ${RUNNER_INSTALL_DIR}/1/run.sh"

# Verify and source the instance 1 runner environment
if [[ ! -f "${RUNNER_INSTALL_DIR}/1/.env" ]]; then
    echo "FAIL: runner .env not found at ${RUNNER_INSTALL_DIR}/1/.env"
    exit 1
fi
# shellcheck source=/dev/null
source "${RUNNER_INSTALL_DIR}/1/.env"

# Verify required runner env vars are present
: "${INVENTORY_DIR:?runner .env missing INVENTORY_DIR}"
: "${INFINITO_DOCKER_VOLUME:?runner .env missing INFINITO_DOCKER_VOLUME}"
: "${COMPOSE_PROJECT_NAME:?runner .env missing COMPOSE_PROJECT_NAME}"
echo "OK: runner .env verified (INVENTORY_DIR=${INVENTORY_DIR}, INFINITO_DOCKER_VOLUME=${INFINITO_DOCKER_VOLUME})"

# In DinD the runner containers are started but registration is skipped
# (entrypoint sleeps). Verify each instance container is running before
# attempting the full end-to-end deploy (which needs the package-cache proxy
# that is unavailable in DinD).
if [[ "${DOCKER_IN_CONTAINER}" == "true" ]]; then
    echo "Verifying runner containers are running in DinD..."
    for i in $(seq 1 "${RUNNER_COUNT}"); do
        state=$(container inspect --format '{{.State.Status}}' "runner-${i}" 2>/dev/null || true)
        if [[ "${state}" != "running" ]]; then
            echo "FAIL: runner-${i} container is not running (state=${state:-not found})"
            exit 1
        fi
        echo "OK: runner-${i} is running"
    done
    echo "SKIP: nested deploy not supported in DinD (DOCKER_IN_CONTAINER=true)"
    exit 0
fi
