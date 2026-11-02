#!/usr/bin/env bash
# Param: MARIADB_HA_BOOTSTRAP  1 on the instance that may initialise an empty data directory
# Param: MARIADB_SEED_PORT     port an empty non-bootstrap instance receives its seed stream on
# Param: ELECTOR_*             options of the writer elector (python -m infinito_elector); without ELECTOR_HOST_ID the stock entrypoint runs (standalone form)
set -euo pipefail

if [ -z "${ELECTOR_HOST_ID:-}" ]; then
  exec docker-entrypoint.sh "$@"
fi

datadir=/var/lib/mysql
ready="${datadir}/.infinito-ha-ready"
recovered="${datadir}/.infinito-ha-recovered"
reseed="${datadir}/.infinito-ha-reseed"
db=""
elector=""

semi_sync_master() {
  gosu mysql mariadb --no-defaults --user="${ELECTOR_MARIADB_LOCAL_USER:?}" --socket="${ELECTOR_MARIADB_SOCKET:?}" \
    --connect-timeout=2 -N -B -e 'SELECT @@GLOBAL.rpl_semi_sync_master_enabled' 2>/dev/null
}

stop_db() {
  local master
  master="$(semi_sync_master || echo unknown)"
  case "$master" in
    0 | OFF)
      kill -TERM "$db" || true # nocheck: shell-or-true -- mariadbd may already have exited
      ;;
    *)
      echo "infinito-ha: semi-sync master is '${master}'; killing mariadbd so recovery drops unacknowledged writes" >&2
      case "$master" in 1 | ON) touch "$recovered" ;; esac
      kill -KILL "$db" || true # nocheck: shell-or-true -- mariadbd may already have exited
      ;;
  esac
  wait "$db" || true # nocheck: shell-or-true -- the exit code of a stopped mariadbd is irrelevant here
}

shutdown() {
  if [ -n "$elector" ] && kill -0 "$elector" 2>/dev/null; then
    kill -TERM "$elector" || true # nocheck: shell-or-true -- the elector may already have exited
    wait "$elector" || true # nocheck: shell-or-true -- the elector's exit code is irrelevant on shutdown
  fi
  if [ -n "$db" ] && kill -0 "$db" 2>/dev/null; then
    stop_db
  fi
  exit "${1:-0}"
}
trap 'shutdown 0' TERM INT

exec 9>"${datadir}/.instance.lock"
if ! flock -x -n 9; then
  echo "infinito-ha: waiting for the previous instance to release ${datadir}" >&2
  flock -x 9
fi

# Param: $1  optional seconds to wait for a sender; a re-seed restarts the task instead of waiting forever
receive_seed() {
  gosu mysql python3 /opt/infinito/seed_relay.py recv "${MARIADB_SEED_PORT}" "${ELECTOR_REPLICATION_PASSWORD_FILE:?}" "$@" | gosu mysql mbstream -x -C "$datadir"
}

donor=""
if [ -e "$reseed" ]; then
  echo "infinito-ha: diverged from the writer; discarding ${datadir} and re-seeding from a peer" >&2
  find "$datadir" -mindepth 1 -maxdepth 1 ! -name .instance.lock ! -name "$(basename "$reseed")" -exec rm -rf {} +
  chown mysql:mysql "$datadir"
  receive_seed 600 &
  seeding=$!
  until donor="$(gosu mysql python3 -m infinito_elector.mariadb_seed request)"; do
    echo "infinito-ha: no peer can donate a seed yet" >&2
    sleep 10
  done
  echo "infinito-ha: ${donor} streams the seed" >&2
  wait "$seeding"
  gosu mysql mariadb-backup --prepare --target-dir="$datadir"
elif [ "${MARIADB_HA_BOOTSTRAP:-0}" != "1" ] && [ ! -d "${datadir}/mysql" ]; then
  echo "infinito-ha: empty data directory, waiting for a seed stream on ${MARIADB_SEED_PORT}" >&2
  chown mysql:mysql "$datadir"
  receive_seed
  gosu mysql mariadb-backup --prepare --target-dir="$datadir"
fi

docker-entrypoint.sh "$@" &
db=$!

if [ -n "$donor" ]; then
  until mariadb-admin --socket="${ELECTOR_MARIADB_SOCKET:?}" ping --silent >/dev/null 2>&1; do
    kill -0 "$db" 2>/dev/null || shutdown 1
    sleep 1
  done
  gosu mysql python3 -m infinito_elector.mariadb_seed attach "$donor"
  rm -f "$reseed"
  touch "$ready"
fi

while [ ! -e "$ready" ]; do
  kill -0 "$db" 2>/dev/null || shutdown 1
  sleep 2
done

until mariadb-admin --socket="${ELECTOR_MARIADB_SOCKET:?}" ping --silent >/dev/null 2>&1; do
  kill -0 "$db" 2>/dev/null || shutdown 1
  sleep 1
done

gosu mysql python3 -m infinito_elector &
elector=$!

exited=""
rc=0
wait -n -p exited "$db" "$elector" || rc=$?
if [ "$exited" = "$elector" ] && [ "$rc" = 3 ]; then
  echo "infinito-ha: former writer must recover before it follows; killing mariadbd" >&2
  kill -KILL "$db"
  exit 1
elif [ "$exited" = "$elector" ] && [ "$rc" = 4 ]; then
  echo "infinito-ha: diverged from the writer; restarting to re-seed from a peer" >&2
  touch "$reseed"
  kill -KILL "$db"
  exit 1
elif [ "$exited" = "$elector" ]; then
  echo "infinito-ha: writer elector exited rc=${rc}; stopping mariadbd" >&2
else
  echo "infinito-ha: mariadbd exited rc=${rc}; stopping the elector" >&2
fi
shutdown 1
