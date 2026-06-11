#!/usr/bin/env bash
# Param: STACK - swarm stack name to probe for converged services
set -euo pipefail

: "${STACK:?STACK env var is required}"

not_running=$(docker stack services --format '{{.Name}} {{.Replicas}}' "$STACK" \
  | awk '{ split($2, r, "/"); if (r[1] != r[2]) print $1 }')

if [ -n "$not_running" ]; then
  echo "not converged: $not_running" >&2
  exit 1
fi
