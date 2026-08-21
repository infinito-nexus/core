#!/bin/sh
set -e

sed -i \
	-e 's#"dbType": "redis"#"dbType": "postgres"#' \
	-e "s#\"url\": \"redis://redis:6379\"#\"host\": \"${ETHERPAD_DB_HOST}\", \"port\": ${ETHERPAD_DB_PORT}, \"database\": \"${ETHERPAD_DB_NAME}\", \"user\": \"${ETHERPAD_DB_USER}\", \"password\": \"${ETHERPAD_DB_PASSWORD}\"#" \
	/opt/etherpad-lite/settings.json

exec /entrypoint.sh
