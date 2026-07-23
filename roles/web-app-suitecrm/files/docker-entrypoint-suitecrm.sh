#!/bin/sh
set -eu

APP_DIR="${SUITECRM_APP_DIR:?SUITECRM_APP_DIR must be baked into the image}"
WEB_USER="${SUITECRM_WEB_USER:?SUITECRM_WEB_USER must be baked into the image}"
WEB_GROUP="${SUITECRM_WEB_GROUP:?SUITECRM_WEB_GROUP must be baked into the image}"
INSTALL_FLAG="${APP_DIR}/public/installed.flag"
SEED_DIR="${SUITECRM_SEED_DIR:?SUITECRM_SEED_DIR must be baked into the image}"
SEED_STAMP="${APP_DIR}/.tree-seeded"

log() { printf '%s %s\n' "[suitecrm-entrypoint]" "$*" >&2; }

if [ ! -d "$APP_DIR" ]; then
  log "ERROR: Application directory '$APP_DIR' does not exist."
  exit 1
fi

TMPDIR="${APP_DIR}/tmp"
export TMPDIR
mkdir -p "$TMPDIR"
chown "$WEB_USER:$WEB_GROUP" "$TMPDIR"
chmod 775 "$TMPDIR"

BOOT_LOCK="${APP_DIR}/.suitecrm-boot.lock.d"

# Exception: the swarm NFS mount forces local_lock=flock, so flock(2) never
# crosses nodes; atomic mkdir on the NFS server is the working cross-replica mutex.
_have_lock=0
_lock_tries=0
while :; do
  if mkdir "$BOOT_LOCK" 2>/dev/null; then
    _have_lock=1
    break
  fi
  # Exception: 1800s exceeds the orchestrator kill ceiling (start_period 20m
  # plus retries), so only a dead leader's lock can be this old.
  _lock_mtime=$(stat -c %Y "$BOOT_LOCK" 2>/dev/null || echo 0)
  if [ "$_lock_mtime" -gt 0 ] && [ $(($(date +%s) - _lock_mtime)) -ge 1800 ]; then
    log "Stale boot lock detected - removing it and retrying."
    rmdir "$BOOT_LOCK" 2>/dev/null || true
    continue
  fi
  if [ -f "$INSTALL_FLAG" ]; then
    break
  fi
  _lock_tries=$((_lock_tries + 1))
  if [ "$_lock_tries" -ge 300 ]; then
    log "ERROR: timed out waiting for the boot lock or install flag."
    exit 1
  fi
  sleep 5
done

if [ "$_have_lock" = "1" ]; then
  trap 'rmdir "$BOOT_LOCK" 2>/dev/null || true' EXIT
  trap 'rmdir "$BOOT_LOCK" 2>/dev/null || true; exit 143' TERM INT

  if [ ! -f "$SEED_STAMP" ]; then
    if [ -f "$INSTALL_FLAG" ]; then
      log "Installed volume without seed stamp - marking as seeded, keeping the live tree."
    else
      log "Seeding SuiteCRM tree from ${SEED_DIR} into ${APP_DIR}..."
      cp -a "${SEED_DIR}/." "${APP_DIR}/"
      log "Seed complete."
    fi
    echo "seeded" > "$SEED_STAMP"
    chown "$WEB_USER:$WEB_GROUP" "$SEED_STAMP"
  fi

  CACHE_REFRESH=0
  if [ ! -f "$INSTALL_FLAG" ]; then
    CACHE_REFRESH=1
    log "SuiteCRM 8 is not installed - performing automated installation..."

    php bin/console suitecrm:app:install \
        -u "$SUITECRM_ADMIN_USERNAME" \
        -p "$SUITECRM_ADMIN_PASSWORD" \
        -U "$SUITECRM_DB_USER" \
        -P "$SUITECRM_DB_PASSWORD" \
        -H "$SUITECRM_DB_HOST" \
        -N "$SUITECRM_DB_NAME" \
        -S "$SUITECRM_URL" \
        -d "no"

    echo "installed" > "$INSTALL_FLAG"
    chown "$WEB_USER:$WEB_GROUP" "$INSTALL_FLAG"

    log "SuiteCRM installation completed successfully."
  else
    log "SuiteCRM already installed - skipping installer."
  fi

  if [ "$CACHE_REFRESH" = "1" ] || [ ! -d "${APP_DIR}/cache/prod" ]; then
    log "Clearing Symfony cache..."
    php bin/console cache:clear --no-warmup || true
    php bin/console cache:warmup || true
  else
    log "Existing prod cache - skipping cache:clear/warmup."
  fi

  # Exception: install/cache:clear above run as root; the legacy language
  # caches they wipe are regenerated lazily by apache as www-data, which
  # cannot write into root-owned cache dirs -> permanent 500 without this.
  chown -R "$WEB_USER:$WEB_GROUP" "${APP_DIR}/cache" "${APP_DIR}/public/legacy/cache" 2>/dev/null || true

  rmdir "$BOOT_LOCK" 2>/dev/null || true
  trap - EXIT TERM INT
else
  log "SuiteCRM installed by another replica - skipping installer and cache pass."
fi

echo "OK" > "${APP_DIR}/public/healthcheck.html"
chown "$WEB_USER:$WEB_GROUP" "${APP_DIR}/public/healthcheck.html"

log "Starting apache2-foreground..."
exec apache2-foreground
