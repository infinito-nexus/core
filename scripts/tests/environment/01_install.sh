#!/usr/bin/env bash
# Install package prerequisites and repository dependencies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/environment/utils/common.sh
source "${SCRIPT_DIR}/utils/common.sh"

bash "${REPO_ROOT}/${INFINITO_PACKAGE_INSTALL_SCRIPT:?}"

echo "Installing Python tooling, Ansible collections, and all repository dependencies."
make install
