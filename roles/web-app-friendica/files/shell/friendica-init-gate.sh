#!/bin/sh
set -eu

APP_DIR="/var/www/html"
VOLUME_VERSION_FILE="$APP_DIR/VERSION"
IMAGE_VERSION_FILE="/usr/src/friendica/VERSION"
INIT_LOCK="$APP_DIR/friendica-init-sync.lock"

slot="${TASK_SLOT:-1}"
case "$slot" in
  ''|*[!0-9]*) slot=1 ;;
esac

if [ "$slot" -ne 1 ]; then
  config_file="${FRIENDICA_CONFIG_FILE:?FRIENDICA_CONFIG_FILE env missing}"
  image_version="$(cat "$IMAGE_VERSION_FILE")"
  while true; do
    if [ -f "$VOLUME_VERSION_FILE" ] && [ -f "$config_file" ]; then
      volume_version="$(cat "$VOLUME_VERSION_FILE" 2>/dev/null || echo '')"
      if [ "$volume_version" = "$image_version" ] \
        && ( exec 9>"$INIT_LOCK"; flock -n 9 ); then
        break
      fi
    fi
    echo "Task slot ${slot}: waiting for slot 1 to finish Friendica init..."
    sleep 10
  done
fi

exec /entrypoint.sh "$@"
