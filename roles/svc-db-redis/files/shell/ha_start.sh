#!/bin/sh
# Param: REDIS_HA_SELF         - service name this instance announces itself by
# Param: REDIS_HA_BOOTSTRAP     - service name of the instance that is master on a fresh cluster
# Param: REDIS_HA_MASTER_NAME   - Sentinel master name
# Param: REDIS_HA_SENTINELS     - space-separated Sentinel service names
# Param: REDIS_HA_INCLUDE       - path of the Ansible-owned include file
# Param: REDIS_HA_CONF          - path of the writable main config, seeded when absent
# Param: REDIS_HA_PORT          - Redis port
# Param: REDIS_HA_SENTINEL_PORT - Sentinel port
# Param: REDIS_HA_SENTINEL_PASSWORD_FILE - file holding the Sentinels' requirepass
set -eu

: "${REDIS_HA_SELF:?}" "${REDIS_HA_BOOTSTRAP:?}" "${REDIS_HA_MASTER_NAME:?}"
: "${REDIS_HA_INCLUDE:?}" "${REDIS_HA_CONF:?}"
port="${REDIS_HA_PORT:?}"
sentinel_port="${REDIS_HA_SENTINEL_PORT:?}"
conf="$REDIS_HA_CONF"

if [ ! -f "$conf" ]; then
  {
    printf 'include %s\n' "$REDIS_HA_INCLUDE"
    if [ "$REDIS_HA_SELF" != "$REDIS_HA_BOOTSTRAP" ]; then
      printf 'replicaof %s %s\n' "$REDIS_HA_BOOTSTRAP" "$port"
    fi
  } >"$conf"
fi

awk -v inc="$REDIS_HA_INCLUDE" '
  BEGIN {
    while ((getline line < inc) > 0) {
      n = split(line, f, " ")
      if (n > 0 && f[1] !~ /^#/) owned[tolower(f[1])] = 1
    }
    print "include " inc
  }
  {
    n = split($0, f, " ")
    key = (n > 0) ? tolower(f[1]) : ""
    if (key == "include" || (key in owned)) next
    print
  }
' "$conf" >"$conf.tmp"
mv "$conf.tmp" "$conf"

REDISCLI_AUTH=$(cat "${REDIS_HA_SENTINEL_PASSWORD_FILE:?}")
export REDISCLI_AUTH
master=$(
  for sentinel in ${REDIS_HA_SENTINELS?}; do
    timeout 3 redis-cli -h "$sentinel" -p "$sentinel_port" --raw \
      SENTINEL get-master-addr-by-name "$REDIS_HA_MASTER_NAME" 2>/dev/null |
      head -1 | awk -F. '!/^[0-9.]+$/ && !/:/ { print $1 }'
  done | grep -E '^[A-Za-z0-9_-]+$' | sort | uniq -c | sort -rn | awk 'NR == 1 { print $2 }'
)

if [ -z "$master" ]; then
  set --
elif [ "$master" = "$REDIS_HA_SELF" ]; then
  set -- --replicaof no one
else
  set -- --replicaof "$master" "$port"
fi

exec redis-server "$conf" --port "$port" --replica-announce-ip "$REDIS_HA_SELF" "$@"
