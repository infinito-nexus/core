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

# Source instance 1 runner environment to verify it is correctly written and
# to inherit runner-specific vars (INFINITO_DOCKER_VOLUME, INVENTORY_DIR, etc.)
# shellcheck source=/dev/null
source "${RUNNER_INSTALL_DIR}/1/.env"

# Unset per-instance networking vars — these are production-only subnet assignments
# that conflict with the CI test stack which uses env.ci defaults (172.30.0.x).
unset SUBNET GATEWAY DNS_IP IP4 BIND_IP COMPOSE_PROJECT_NAME INFINITO_RUNNER_PREFIX

# Deploy a real app through the runner's Docker environment to prove it works end-to-end
APPS=web-app-matomo make -C "${REPO_ROOT}" deploy-fresh-purged-apps
