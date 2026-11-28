#!/bin/bash
# Param: STACK    - swarm stack of the engine; also the Sentinel master name (e.g. redis)
# Param: INSTANCE - instance service key (e.g. redis-mgr-01); its host's Sentinel is asked
#
# Exit codes:
#   0   Sentinel names the instance as master, by announced hostname or by its task IP
#   1   Sentinel names another master
#   2   Sentinel could not be asked or gave no usable answer
#   64  missing args
set -u

STACK="${1:-}"
INSTANCE="${2:-}"
if [ -z "$STACK" ] || [ -z "$INSTANCE" ]; then
  echo "primary-probe-redis: STACK and INSTANCE required" >&2
  exit 64
fi

HOST_ID="${INSTANCE#"${STACK}"-}"
CID=$("$(dirname "$0")/resolve-container-id" "$STACK" "${STACK}-sentinel-${HOST_ID}" 2>/dev/null) || exit 2

# shellcheck disable=SC2016  # single quotes defer expansion to the sentinel container's shell
ANSWER=$(container exec "$CID" sh -c \
  'REDISCLI_AUTH=$(cat "$SENTINEL_PASSWORD_FILE") exec redis-cli -p "$SENTINEL_PORT" SENTINEL get-master-addr-by-name "$SENTINEL_MASTER_NAME"' \
  2>/dev/null | head -1) || exit 2

case "$ANSWER" in
  "" | *:*) exit 2 ;;
  *[!0-9.]*)
    [ "${ANSWER%%.*}" = "$INSTANCE" ] && exit 0
    exit 1
    ;;
esac

if container exec "$CID" getent hosts "tasks.${STACK}_${INSTANCE}" 2>/dev/null \
  | awk '{ print $1 }' | grep -qxF "$ANSWER"; then
  exit 0
fi
exit 1
