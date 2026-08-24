#!/usr/bin/env bash
set -eo pipefail

MARKER="/var/www/storage/.docker.init"

until [ -e "${MARKER}" ]; do
  echo "worker: waiting for Pixelfed bootstrap marker ${MARKER} ..."
  sleep 5
done

exec /worker-entrypoint.sh "$@"
