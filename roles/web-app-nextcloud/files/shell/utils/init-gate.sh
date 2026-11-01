#!/bin/sh
set -eu

APP_DIR="/var/www/html"
CONFIG_PHP="$APP_DIR/config/config.php"
VERSION_PHP="$APP_DIR/version.php"
OCC="$APP_DIR/occ"
INIT_LOCK="$APP_DIR/nextcloud-init-sync.lock"

app_user="${NEXTCLOUD_INIT_GATE_USER:?NEXTCLOUD_INIT_GATE_USER env missing}"

occ_status() {
  timeout 120 su "$app_user" -s /bin/sh -c "php $OCC status" 2>/dev/null || true
}

init_lock_free() {
  ( exec 9>"$INIT_LOCK"; flock -n 9 )
}

slot="${TASK_SLOT:-1}"
case "$slot" in
  ''|*[!0-9]*) slot=1 ;;
esac

if [ "$slot" -ne 1 ]; then
  while true; do
    status=''
    if init_lock_free && [ -f "$CONFIG_PHP" ] && [ -f "$OCC" ]; then
      status="$(occ_status)"
    fi

    ready=1
    case "$status" in *"- installed: true"*) ;; *) ready=0 ;; esac
    case "$status" in *"- maintenance: false"*) ;; *) ready=0 ;; esac
    case "$status" in *"- needsDbUpgrade: false"*) ;; *) ready=0 ;; esac

    if [ "$ready" -eq 1 ]; then
      break
    fi

    echo "Task slot ${slot}: waiting for a consistent Nextcloud installation..."
    sleep 10
  done
elif [ -f "$VERSION_PHP" ] && [ -f "$OCC" ] && init_lock_free; then
  case "$(occ_status)" in
    *"- installed: false"*)
      echo "Task slot ${slot}: $VERSION_PHP exists but Nextcloud reports installed: false. An earlier installation attempt failed after copying the source tree, and the upstream entrypoint never retries it. Read that attempt's error in the earlier container's log, then drop the Nextcloud database and empty the volume before redeploying." >&2
      exit 1
      ;;
  esac
fi

exec /entrypoint.sh "$@"
