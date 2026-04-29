#!/usr/bin/env bash
# In-container helper: run the standard entry.sh bootstrap.
#
# Designed to be called via `docker exec` or
# `cli.deploy.development exec -- bash <this-path>`. The repo is mounted
# at /opt/src/infinito by the dev compose stack.
set -euo pipefail
cd /opt/src/infinito
./scripts/docker/entry.sh true
