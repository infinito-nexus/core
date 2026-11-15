#!/usr/bin/env bash
# Args: none
#
# Env of the Workspaces project:
#   BAO_ADDR, BAO_CACERT     the OpenBao whose task entities go
#   BAO_TASK_ENTITIES_ROLE   the task token role of prune task entities
#   BAO_JWT_TOKEN_TTLS       JSON object of the token_max_ttl of every task token role
#   SEMAPHORE_JWT            the task token Semaphore hands every task
#   INFINITO_SRC_DIR         the core tree of the runner image
set -euo pipefail

SCRIPT="task-entities.sh"
here="$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib.sh
source "${here}/lib.sh"

refuse_arguments 0 "$@"

: "${BAO_JWT_TOKEN_TTLS:?the project environment names no task token ttls}"
BAO_ROLE="${BAO_TASK_ENTITIES_ROLE:?the project environment names no task entities role}" \
	exec python3 "${here}/../../python/prune/task_entities.py"
