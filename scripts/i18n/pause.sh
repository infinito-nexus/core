#!/usr/bin/env bash
set -euo pipefail

# Pause the translation (tools) lane container so a routine or cron can hold the
# machine's gate lock without the lane sending requests, and never touches
# Docker directly. The lane keeps its loaded models and
# connections and continues exactly where it paused (make i18n-resume).
# Inputs (env):
#   TOOLS_LANE_CONTAINER - the running tools lane container name; required

docker pause "${TOOLS_LANE_CONTAINER:?set it to the running tools lane container name}"
