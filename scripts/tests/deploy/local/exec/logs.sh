#!/usr/bin/env bash
set -euo pipefail

# Dump the logs of a deployed app container of the local compose stack, through
# the repository's own `container` wrapper.
#
# Usage:
#   app=<container> [tail=<lines>] scripts/tests/deploy/local/exec/logs.sh  # nocheck: self-path-reference
#
# Environment:
#   app   Container name of the deployed app (e.g. litellm).
#   tail  Number of trailing lines to print. Default: 200.
#
# Examples:
#   app=litellm tail=80 scripts/tests/deploy/local/exec/logs.sh  # nocheck: self-path-reference

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${app:?app=<container> required, e.g. app=litellm}"

exec bash "${SCRIPT_DIR}/container.sh" container logs --tail "${tail:-200}" "${app}"
