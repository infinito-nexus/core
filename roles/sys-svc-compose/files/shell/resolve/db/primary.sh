#!/bin/bash
# Param: STACK  - swarm stack of the engine (e.g. postgres)
# Param: ENGINE - engine word; its own probe primary-probe-<ENGINE> sits next to this script
#
# Exit codes:
#   0   success -- prints the container id of the primary
#   64  missing args or no probe installed for the engine
#   65  no running instance answered as primary
set -eu

STACK="${1:-}"
ENGINE="${2:-}"
if [ -z "$STACK" ] || [ -z "$ENGINE" ]; then
  echo "resolve-db-primary: STACK and ENGINE required" >&2
  exit 64
fi

BIN_DIR="$(dirname "$0")"
PROBE="${BIN_DIR}/primary-probe-${ENGINE}"
[ -x "$PROBE" ] || {
  echo "resolve-db-primary: no primary probe for engine '$ENGINE' at $PROBE" >&2; exit 64; }

instances() {
  container service ls \
    --filter "name=${STACK}_${ENGINE}-" \
    --format '{{.Name}}' 2>/dev/null | sed "s/^${STACK}_//" | sort
}

primary_key() {
  local key
  for key in $(instances); do
    if "$PROBE" "$STACK" "$key" >/dev/null 2>&1; then
      echo "$key"
      return 0
    fi
  done
  return 1
}

KEY=$(primary_key) || KEY=""
[ -n "$KEY" ] || {
  echo "resolve-db-primary: no primary found for '$ENGINE' in stack '$STACK'" >&2; exit 65; }

exec "${BIN_DIR}/resolve-container-id" "$STACK" "$KEY"
