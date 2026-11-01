#!/bin/sh
# Param: SENTINEL_SELF          - service name this Sentinel announces itself by
# Param: SENTINEL_PEERS         - space-separated service names of the other Sentinels
# Param: SENTINEL_INSTANCES     - space-separated service names of the current Redis instances; known-replica
#                                 entries of other hosts are dropped, as Sentinel refuses to start on a
#                                 hostname it cannot resolve
# Param: SENTINEL_MASTER_NAME   - Sentinel master name
# Param: SENTINEL_BOOTSTRAP     - instance service that is master on a fresh cluster
# Param: SENTINEL_AUTH_USER     - Redis ACL user Sentinel logs in as
# Param: SENTINEL_PASSWORD_FILE - file holding that user's password; also the Sentinels' own requirepass
# Param: SENTINEL_CONF          - path of the writable Sentinel config
# Param: SENTINEL_QUORUM        - quorum
# Param: SENTINEL_DOWN_AFTER_MS - down-after-milliseconds
# Param: SENTINEL_FAILOVER_MS   - failover-timeout
# Param: SENTINEL_PARALLEL_SYNCS - parallel-syncs
# Param: SENTINEL_PORT          - Sentinel port
# Param: REDIS_PORT             - Redis port
# Param: SENTINEL_PEER_WAIT_S   - seconds a restarting Sentinel keeps asking its peers for the current
#                                 master (default 120); the saved master may be stale after a failover
#                                 and the node's DNS may not resolve the peers yet
set -eu

: "${SENTINEL_SELF:?}" "${SENTINEL_MASTER_NAME:?}" "${SENTINEL_BOOTSTRAP:?}"
: "${SENTINEL_AUTH_USER:?}" "${SENTINEL_PASSWORD_FILE:?}" "${SENTINEL_CONF:?}"
name="$SENTINEL_MASTER_NAME"
port="${SENTINEL_PORT:?}"
redis_port="${REDIS_PORT:?}"
conf="$SENTINEL_CONF"
password=$(cat "$SENTINEL_PASSWORD_FILE")
REDISCLI_AUTH="$password"
export REDISCLI_AUTH

touch "$conf"

instances=" ${SENTINEL_INSTANCES:?} "
sentinels=" $SENTINEL_SELF ${SENTINEL_PEERS?} "

peer_master() {
  for peer in ${SENTINEL_PEERS?}; do
    timeout 3 redis-cli -h "$peer" -p "$port" --raw \
      SENTINEL get-master-addr-by-name "$name" 2>/dev/null |
      head -1 | awk -F. '!/^[0-9.]+$/ && !/:/ { print $1 }'
  done | grep -E '^[A-Za-z0-9_-]+$' | sort | uniq -c | sort -rn | awk -v instances="$instances" '
    index(instances, " " $2 " ") { print $2; exit }'
}

saved=$(awk -v n="$name" '$1 == "sentinel" && $2 == "monitor" && $3 == n { print $4 }' "$conf" | tail -1)
case "$instances" in *" $saved "*) ;; *) saved="" ;; esac
master=$(peer_master)
if [ -z "$master" ] && [ -n "$saved" ]; then
  deadline=$(($(date +%s) + ${SENTINEL_PEER_WAIT_S:-120}))
  while [ -z "$master" ] && [ "$(date +%s)" -lt "$deadline" ]; do
    sleep 2
    master=$(peer_master)
  done
fi
[ -n "$master" ] || master="$saved"
[ -n "$master" ] || master="$SENTINEL_BOOTSTRAP"

{
  printf 'port %s\n' "$port"
  printf 'requirepass %s\n' "$password"
  printf 'dir %s\n' "$(dirname "$conf")"
  printf 'sentinel resolve-hostnames yes\n'
  printf 'sentinel announce-hostnames yes\n'
  printf 'sentinel announce-ip %s\n' "$SENTINEL_SELF"
  printf 'sentinel monitor %s %s %s %s\n' "$name" "$master" "$redis_port" "${SENTINEL_QUORUM:?}"
  printf 'sentinel auth-user %s %s\n' "$name" "$SENTINEL_AUTH_USER"
  printf 'sentinel auth-pass %s %s\n' "$name" "$password"
  printf 'sentinel down-after-milliseconds %s %s\n' "$name" "${SENTINEL_DOWN_AFTER_MS:?}"
  printf 'sentinel failover-timeout %s %s\n' "$name" "${SENTINEL_FAILOVER_MS:?}"
  printf 'sentinel parallel-syncs %s %s\n' "$name" "${SENTINEL_PARALLEL_SYNCS:?}"
  awk -v instances="$instances" -v sentinels="$sentinels" '
    $1 != "sentinel" { next }
    $2 ~ /^(myid|current-epoch|config-epoch|leader-epoch)$/ { print; next }
    { split($4, host, ".") }
    $2 == "known-replica" && index(instances, " " host[1] " ") { print; next }
    $2 == "known-sentinel" && index(sentinels, " " host[1] " ") { print }
  ' "$conf"
} >"$conf.tmp"
mv "$conf.tmp" "$conf"

exec redis-server "$conf" --sentinel
