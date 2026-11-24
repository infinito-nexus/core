#!/usr/bin/env bash
set -euo pipefail

# Param:
#   $@                        the deploy command and its arguments, run as the job from this checkout
#   INFINITO_DEPLOY_VIA_POOL  forced to false for the command, so a job never submits itself to the pool again

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

if (($# == 0)); then
	echo "[job-entry] a deploy command is required" >&2
	exit 2
fi

cd "${REPO_ROOT}"
export INFINITO_DEPLOY_VIA_POOL=false

echo "[job-entry] start: $* (checkout ${REPO_ROOT})"
exec "$@"
