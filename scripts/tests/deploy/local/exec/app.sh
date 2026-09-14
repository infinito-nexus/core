#!/usr/bin/env bash
set -euo pipefail

# Run a one-off command inside a deployed app container of the local compose
# stack, through the repository's own `container` wrapper.
#
# Usage:
#   app=<container> cmd='<command>' scripts/tests/deploy/local/exec/app.sh  # nocheck: self-path-reference
#
# Environment:
#   app  Container name of the deployed app (e.g. flowise).
#   cmd  Command executed inside that container via `sh -lc`.
#
# Examples:
#   app=flowise cmd='wget -qO- http://localhost:3000/api/v1/ping' scripts/tests/deploy/local/exec/app.sh  # nocheck: self-path-reference

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${app:?app=<container> required, e.g. app=flowise}"
: "${cmd:?cmd='<command>' required}"

exec bash "${SCRIPT_DIR}/container.sh" container exec -i "${app}" sh -lc "${cmd}"
