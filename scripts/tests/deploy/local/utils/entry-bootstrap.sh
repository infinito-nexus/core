#!/usr/bin/env bash
# In-container helper: run the standard entry.sh bootstrap.
#
# Designed to be called via `docker exec` or
# `cli.administration.deploy.development exec -- bash <this-path>`. The repo is mounted
# at ${INFINITO_SRC_DIR} by the dev compose stack.
set -euo pipefail
: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR must be set by the container environment}"
cd "${INFINITO_SRC_DIR}"
./scripts/docker/entry.sh --compile -- true
