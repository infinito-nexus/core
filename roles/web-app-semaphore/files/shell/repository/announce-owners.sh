#!/usr/bin/env bash
# Args: none
#
# Env: REQUIRED_ENV of roles/web-app-semaphore/files/python/announce_owners.py,
#   which the environment of the scheduled export templates and Semaphore
#   (SEMAPHORE_JWT) set; BAO_CACERT under self_signed, EGRESS_PROXY on the
#   export runner
set -euo pipefail

SCRIPT="announce-owners.sh"
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
# shellcheck source=lib.sh
source "${here}/lib.sh"

refuse_arguments 0 "$@"

root="$(cd "${here}/../../../../.." && pwd)"
PYTHONPATH="${root}" exec python3 "${root}/roles/web-app-semaphore/files/python/announce_owners.py"
