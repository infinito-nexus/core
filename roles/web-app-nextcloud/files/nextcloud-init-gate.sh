#!/bin/sh
set -eu

APP_DIR="/var/www/html"
CONFIG_PHP="$APP_DIR/config/config.php"
VOLUME_VERSION_PHP="$APP_DIR/version.php"
IMAGE_VERSION_PHP="/usr/src/nextcloud/version.php"

slot="${TASK_SLOT:-1}"
case "$slot" in
  ''|*[!0-9]*) slot=1 ;;
esac

if [ "$slot" -ne 1 ]; then
  image_version="$(php -r "require '$IMAGE_VERSION_PHP'; echo implode('.', \$OC_Version);")"
  while true; do
    if [ -f "$VOLUME_VERSION_PHP" ] && [ -f "$CONFIG_PHP" ]; then
      volume_version="$(php -r "require '$VOLUME_VERSION_PHP'; echo implode('.', \$OC_Version);" 2>/dev/null || echo '')"
      if [ "$volume_version" = "$image_version" ]; then
        break
      fi
    fi
    echo "Task slot ${slot}: waiting for slot 1 to finish Nextcloud init..."
    sleep 10
  done
fi

exec /entrypoint.sh "$@"
