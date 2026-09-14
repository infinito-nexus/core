#!/usr/bin/env bash
set -euo pipefail

# Restart a single deployed app container of the local compose stack, through
# the repository's own `container` wrapper.
#
# Usage:
#   app=<container> scripts/tests/deploy/local/exec/restart.sh  # nocheck: self-path-reference
#
# Environment:
#   app   Container name of the deployed app (e.g. nextcloud).
#
# Examples:
#   app=nextcloud scripts/tests/deploy/local/exec/restart.sh  # nocheck: self-path-reference

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${app:?app=<container> required, e.g. app=nextcloud}"

exec bash "${SCRIPT_DIR}/container.sh" container restart "${app}"
