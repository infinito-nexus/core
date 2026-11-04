#!/usr/bin/env bash
set -euo pipefail

# Resume the translation (tools) lane container that make i18n-pause paused,
# with its loaded models and connections intact, without touching Docker
# directly.
# Inputs (env):
#   TOOLS_LANE_CONTAINER - the running tools lane container name; required

docker unpause "${TOOLS_LANE_CONTAINER:?set it to the running tools lane container name}"
