#!/usr/bin/env bash
set -euo pipefail

set -a
# shellcheck source=/dev/null
. "${HOME}/.config/claude-gateway/env"
set +a
exec claude "$@"
