#!/usr/bin/env bash
#
# Best-effort dump of pg_hba.conf for diagnostics. Used by
# roles/svc-db-postgres/tasks/02_init.yml when the readiness wait
# fails. The Postgres container address and admin password are
# read from the environment so this script stays Jinja-free and
# secrets never enter the process arg list.
#
# Required environment:
#   POSTGRES_CONTAINER_ADDRESS   exec address of the postgres container
#   PGPASSWORD                   postgres superuser password
set -eu

: "${POSTGRES_CONTAINER_ADDRESS:?POSTGRES_CONTAINER_ADDRESS not set}"
: "${PGPASSWORD:?PGPASSWORD not set}"
export PGPASSWORD

hba="$(container exec --env "PGPASSWORD=$PGPASSWORD" "$POSTGRES_CONTAINER_ADDRESS" \
  psql -U postgres -d postgres -Atc 'SHOW hba_file;' 2>/dev/null || true)"

if [ -n "$hba" ]; then
  echo "hba_file=$hba"
  container exec "$POSTGRES_CONTAINER_ADDRESS" sh -lc \
    "sed -n '1,200p' \"$hba\" 2>/dev/null || true"
else
  echo "hba_file could not be determined"
fi
