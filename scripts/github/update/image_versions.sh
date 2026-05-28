#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"
make dotenv >/dev/null
set -a
# shellcheck disable=SC1091
. .env
set +a
python3 -m cli.contributing.update.docker "$@"
