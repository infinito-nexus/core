#!/usr/bin/env bash
# Install dependencies and prepare the environment for deployment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/environment/utils/common.sh
source "${SCRIPT_DIR}/utils/common.sh"

cd "${REPO_ROOT}"

echo "Bootstrapping the development environment: DNS, AppArmor, IPv6, and lint tooling."
make environment-bootstrap

echo "Starting the local compose stack (builds the image if missing)."
make compose-up
