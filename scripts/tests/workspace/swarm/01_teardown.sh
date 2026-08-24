#!/usr/bin/env bash
# Release the development stack the base track started, so the swarm cluster
# runs alone. The swarm steps only need the node image on the host daemon,
# which 03_build.sh put there and `make compose-down` does not touch.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/../utils/teardown.sh"
