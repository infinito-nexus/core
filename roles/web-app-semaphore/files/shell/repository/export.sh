#!/usr/bin/env bash
# Args: none
#
# Env: REQUIRED_ENV of roles/web-app-semaphore/files/python/export.py, which the
#   survey (WORKSPACE, EXPORT_FOR), the project environment and Semaphore
#   (SEMAPHORE_JWT, SEMAPHORE_TASK_ID) set; BAO_CACERT under self_signed
set -euo pipefail

if [ "$#" -ne 0 ]; then
	echo "usage: export.sh" >&2
	exit 2
fi

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../../../.." && pwd)"
PYTHONPATH="${root}" exec python3 "${root}/roles/web-app-semaphore/files/python/export.py"
