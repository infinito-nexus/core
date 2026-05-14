#!/usr/bin/env bash
# Verifies that the svc-runner role works by deploying a real app through the
# runner's Docker environment. Variables are sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${RUNNER_INSTALL_DIR:?}"
: "${RUNNER_USER:?}"

# Skip gracefully when svc-runner was never deployed on this host
if ! id "${RUNNER_USER}" >/dev/null 2>&1; then
    echo "SKIP: ${RUNNER_USER} user absent — svc-runner not deployed on this host"
    exit 0
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

# Load default deploy env (sets INFINITO_DISTRO, TEST_DEPLOY_TYPE, etc.)
# shellcheck source=scripts/meta/env/all.sh
source "${REPO_ROOT}/scripts/meta/env/all.sh"

# Source instance 1 runner environment — provides COMPOSE_PROJECT_NAME, SUBNET,
# INFINITO_DOCKER_VOLUME, and other runner-specific Docker settings
# shellcheck source=/dev/null
source "${RUNNER_INSTALL_DIR}/1/.env"

# Deploy a real app through the runner's Docker environment to prove it works end-to-end
APPS=web-app-matomo make -C "${REPO_ROOT}" deploy-fresh-purged-apps
