#!/bin/sh
set -eu

: "${POSTGRES_USER:?set by the upstream compose file}"
: "${ETHERPAD_DB_NAME:?set in env.j2 and broadcast to every service}"

if ! psql --username "${POSTGRES_USER}" --dbname postgres -tAc \
	"SELECT 1 FROM pg_database WHERE datname = '${ETHERPAD_DB_NAME}'" | grep -q 1; then
	psql --username "${POSTGRES_USER}" --dbname postgres \
		-c "CREATE DATABASE \"${ETHERPAD_DB_NAME}\""
fi
