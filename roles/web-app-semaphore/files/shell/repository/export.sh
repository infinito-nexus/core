#!/usr/bin/env bash
# Args: none
#
# Env: REQUIRED_ENV of roles/web-app-semaphore/files/python/export.py, which the
#   survey (WORKSPACE, EXPORT_FOR), the project environment and Semaphore
#   (SEMAPHORE_JWT, SEMAPHORE_TASK_ID) set; BAO_CACERT under self_signed
set -euo pipefail

SCRIPT="export.sh"
# shellcheck source=SCRIPTDIR/lib.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib.sh"

refuse_arguments 0 "$@"

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../../../.." && pwd)"
PYTHONPATH="${root}" exec python3 "${root}/roles/web-app-semaphore/files/python/export.py"
