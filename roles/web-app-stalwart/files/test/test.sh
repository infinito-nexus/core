#!/usr/bin/env bash
# Stalwart e2e coordinator: test-e2e-cli runs this with test.env exported, and each
# scenario below inherits that env, self-skipping when its scenario is not deployed.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

bash "${SCRIPT_DIR}/test_migration.sh"
