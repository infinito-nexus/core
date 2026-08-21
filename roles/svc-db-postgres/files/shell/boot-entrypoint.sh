#!/bin/sh
set -e
pid="${PGDATA:?}/postmaster.pid"
if [ -f "$pid" ] && [ ! -s "$pid" ]; then rm -f "$pid"; fi
exec docker-entrypoint.sh "$@"
