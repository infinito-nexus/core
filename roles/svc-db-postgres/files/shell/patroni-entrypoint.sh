#!/bin/sh
# Param: $1 - mounted patroni.yml secret (root-owned, 0400)
# Param: $2 - postgres-owned copy Patroni and patronictl read
# Param: DB_REPLICATION_SUBNET - CIDR of the engine-internal overlay pg_hba admits replication from
# Param: DB_POSTGRES_PORT / DB_PATRONI_API_PORT - ports advertised to the peers
# Param: DB_BOOTSTRAP_ALLOWED - "true" only on the instance that may initdb a new cluster; any other empty
#        member waits for an initialized cluster
# Param: DB_BOOTSTRAP_GRACE - seconds an empty bootstrap instance leaves peers with data to claim the cluster
set -e
# shellcheck disable=SC2046 # hostname -I prints one address per word, each a separate argument
address=$(python3 -c 'import ipaddress, sys; net = ipaddress.ip_network(sys.argv[1]); print(next(a for a in sys.argv[2:] if ipaddress.ip_address(a) in net))' "${DB_REPLICATION_SUBNET:?}" $(hostname -I))
export PATRONI_POSTGRESQL_CONNECT_ADDRESS="${address}:${DB_POSTGRES_PORT:?}"
export PATRONI_RESTAPI_CONNECT_ADDRESS="${address}:${DB_PATRONI_API_PORT:?}"
install -o postgres -g postgres -m 0600 "${1:?}" "${2:?}"
mkdir -p "${PGDATA:?}"
chown postgres:postgres "$(dirname "$PGDATA")" "$PGDATA"
chmod 0700 "$PGDATA"
pid="$PGDATA/postmaster.pid"
if [ -f "$pid" ] && [ ! -s "$pid" ]; then rm -f "$pid"; fi
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  if [ "${DB_BOOTSTRAP_ALLOWED:-false}" = "true" ]; then
    sleep "${DB_BOOTSTRAP_GRACE:?}"
  else
    until gosu postgres patronictl -c "$2" list 2>/dev/null | head -n 1 | grep -qE 'Cluster: [^ ]+ \([0-9]+\)'; do
      echo "patroni-entrypoint: waiting for an initialized cluster before cloning" >&2
      sleep 5
    done
  fi
fi
exec gosu postgres patroni "$2"
