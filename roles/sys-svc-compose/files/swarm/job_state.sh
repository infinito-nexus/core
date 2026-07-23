#!/bin/sh
# Param: JOB (env) - swarm service name of a one-shot job (install, import).
# Exit: 0 newest task Complete; 2 Shutdown; 1 pending (includes
# Failed/Rejected, since swarm may still start the next attempt).
set -eu
state="$(container service ps "$JOB" --no-trunc --format '{{.CurrentState}} {{.Error}}' | head -1)"
case "$state" in
  Complete*) exit 0 ;;
  Shutdown*) echo "one-shot job stopped without success: $state" >&2; exit 2 ;;
  Failed*|Rejected*) echo "attempt state: $state" >&2; exit 1 ;;
  *) exit 1 ;;
esac
