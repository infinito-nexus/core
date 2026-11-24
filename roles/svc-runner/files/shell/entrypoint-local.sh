#!/usr/bin/env bash
set -euo pipefail

# Param:
#   COMPOSE_PROJECT_NAME       the runner's job stack, also its name in the queue
#   INFINITO_RUNNER_QUEUE_DIR  the job queue the runner takes its jobs from
#   INFINITO_RUNNER_INSTALL_DIR the runner's own directory, which holds its copy and nothing a job may replace
#   INFINITO_RUNNER_CHECKOUT   the folder of it every job's checkout is copied into and runs from
#   INFINITO_RUNNER_IMAGE      the toolchain image the runner runs, which removes the copy of the job before as root
#   RUNNER_SRC_DIR             the checkout, below a mounted worktree root, whose pool loop runs

: "${COMPOSE_PROJECT_NAME:?COMPOSE_PROJECT_NAME must be set}"
: "${INFINITO_RUNNER_QUEUE_DIR:?INFINITO_RUNNER_QUEUE_DIR must be set}"
: "${INFINITO_RUNNER_INSTALL_DIR:?INFINITO_RUNNER_INSTALL_DIR must be set}"
: "${INFINITO_RUNNER_CHECKOUT:?INFINITO_RUNNER_CHECKOUT must be set}"
: "${INFINITO_RUNNER_IMAGE:?INFINITO_RUNNER_IMAGE must be set}"
: "${RUNNER_SRC_DIR:?RUNNER_SRC_DIR must be set}"

cd "${RUNNER_SRC_DIR}"
export PYTHONPATH="${RUNNER_SRC_DIR}"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -m cli.administration.deploy.pool.serve
