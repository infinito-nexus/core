#!/usr/bin/env bash
set -euo pipefail

# Param:
#   APPS                       the applications the Semaphore task deploys, from its survey
#   INFINITO_POOL_RUNNER_NAME  the pool runner whose Semaphore runner runs the task; the job is pinned to it
#   INFINITO_RUNNER_QUEUE_DIR  the job queue of the runner pool
#   RUNNER_SRC_DIR             the checkout the job deploys from, which the pool runner copies and runs entry.sh in

: "${APPS:?APPS must be set by the task survey}"
: "${INFINITO_POOL_RUNNER_NAME:?INFINITO_POOL_RUNNER_NAME must be set}"
: "${INFINITO_RUNNER_QUEUE_DIR:?INFINITO_RUNNER_QUEUE_DIR must be set}"
: "${RUNNER_SRC_DIR:?RUNNER_SRC_DIR must be set}"

cd "${RUNNER_SRC_DIR}"
export PYTHONPATH="${RUNNER_SRC_DIR}"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -m utils.runner.pinned compose-deploy "apps=${APPS}"
