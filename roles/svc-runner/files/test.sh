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

# Propagate the outer CI distro so the nested deploy uses the same image.
# When test.sh runs inside a DinD container (e.g. fedora), all.sh defaults
# INFINITO_DISTRO=debian which triggers a debian nested DinD — that fails
# because python3-apt is missing in its apt sources. Using the outer distro
# (DISTROS env set by the GitHub Actions job) fixes the image mismatch.
if [[ -z "${INFINITO_DISTRO:-}" && -n "${DISTROS:-}" ]]; then
    export INFINITO_DISTRO="${DISTROS%% *}"
fi

# Load default deploy env (sets INFINITO_DISTRO, TEST_DEPLOY_TYPE, etc.)
# shellcheck source=scripts/meta/env/all.sh
source "${REPO_ROOT}/scripts/meta/env/all.sh"

# Unset per-instance networking vars — production-only subnet assignments
# that conflict with the CI test stack which uses env.ci defaults (172.30.0.x).
unset SUBNET GATEWAY DNS_IP IP4 BIND_IP COMPOSE_PROJECT_NAME INFINITO_RUNNER_PREFIX

# Deploy a real app through the runner's Docker environment to prove it works end-to-end
APPS=web-app-matomo make -C "${REPO_ROOT}" deploy-fresh-purged-apps
