#!/bin/sh
set -eu

APP_DIR="/var/www/html"
CONFIG_PHP="$APP_DIR/config/config.php"
OCC="$APP_DIR/occ"
INIT_LOCK="$APP_DIR/nextcloud-init-sync.lock"
IMAGE_VERSION_PHP="/usr/src/nextcloud/version.php"

slot="${TASK_SLOT:-1}"
case "$slot" in
  ''|*[!0-9]*) slot=1 ;;
esac

if [ "$slot" -ne 1 ]; then
  app_user="${NEXTCLOUD_INIT_GATE_USER:?NEXTCLOUD_INIT_GATE_USER env missing}"
  image_version="$(php -r "require '$IMAGE_VERSION_PHP'; echo implode('.', \$OC_Version);")"

  while true; do
    status=''
    if ( exec 9>"$INIT_LOCK"; flock -n 9 ) && [ -f "$CONFIG_PHP" ] && [ -f "$OCC" ]; then
      status="$(su "$app_user" -s /bin/sh -c "php $OCC status" 2>/dev/null || true)"
    fi

    ready=1
    case "$status" in *"- installed: true"*) ;; *) ready=0 ;; esac
    case "$status" in *"- maintenance: false"*) ;; *) ready=0 ;; esac
    case "$status" in *"- needsDbUpgrade: false"*) ;; *) ready=0 ;; esac
    case "$status" in *"- version: $image_version"*) ;; *) ready=0 ;; esac

    if [ "$ready" -eq 1 ]; then
      break
    fi

    echo "Task slot ${slot}: waiting for slot 1 to finish Nextcloud init..."
    sleep 10
  done
fi

exec /entrypoint.sh "$@"
