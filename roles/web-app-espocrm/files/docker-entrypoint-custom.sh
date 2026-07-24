#!/bin/sh
# Serialize the image entrypoint's first-boot install/upgrade across N swarm
# replicas that share the /var/www/html NFS volume, then start the server
# ourselves on every replica. With --wait-ready <cmd...> instead: block until
# the ready marker exists, then exec cmd. Swarm ignores depends_on, and any
# EspoCRM PHP run mid-install (daemon/websocket app-check) leaves NFS
# silly-rename files in data/cache that make the installer's rm/rebuild fail.
set -eu

log() { printf '%s %s\n' "[entrypoint]" "$*" >&2; }

bool_norm () {
  v="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' 2>/dev/null || true)"
  case "$v" in
    1|true|yes|on)  echo "true" ;;
    0|false|no|off|"") echo "false" ;;
    *) echo "false" ;;
  esac
}

APP_DIR="/var/www/html"
SESSION_DIR="${APP_DIR}/data/.sessions"
BOOT_LOCK="${APP_DIR}/data/.infinito-espocrm-boot.lock.d"
READY_MARKER="${APP_DIR}/data/.infinito-espocrm-boot.ready"
ORIG_ENTRYPOINT="/usr/local/bin/docker-entrypoint.sh"

if [ "${1:-}" = "--wait-ready" ]; then
  shift
  if [ "$#" -eq 0 ]; then
    log "ERROR: --wait-ready requires a command to exec."
    exit 1
  fi
  if [ ! -f "$READY_MARKER" ]; then
    log "Waiting for the boot ready marker before starting: $*"
  fi
  waited=0
  until [ -f "$READY_MARKER" ]; do
    if [ "$waited" -ge "${ESPOCRM_WAIT_READY_TIMEOUT_S:-1800}" ]; then
      log "ERROR: ready marker did not appear within ${ESPOCRM_WAIT_READY_TIMEOUT_S:-1800}s; giving up."
      exit 1
    fi
    sleep 5
    waited=$((waited + 5))
  done
  log "Exec: $*"
  exec "$@"
fi

MAINTENANCE="$(bool_norm "${ESPOCRM_SEED_MAINTENANCE_MODE:-}")"
CRON_DISABLED="$(bool_norm "${ESPOCRM_SEED_CRON_DISABLED:-}")"
USE_CACHE="$(bool_norm "${ESPOCRM_SEED_USE_CACHE:-}")"
log "Flags: maintenance=${MAINTENANCE} cron_disabled=${CRON_DISABLED} use_cache=${USE_CACHE}"

: "${ESPOCRM_SCRIPT_SEED:?missing ESPOCRM_SCRIPT_SEED}"
SEED_CONFIG_SCRIPT="${ESPOCRM_SCRIPT_SEED}"

_have_lock=0
_lock_tries=0
while :; do
  if [ -f "$READY_MARKER" ]; then
    break
  fi
  if mkdir "$BOOT_LOCK" 2>/dev/null; then
    _have_lock=1
    break
  fi
  _lock_mtime=$(stat -c %Y "$BOOT_LOCK" 2>/dev/null || echo 0)
  if [ "$_lock_mtime" -gt 0 ] && [ $(($(date +%s) - _lock_mtime)) -ge 1800 ]; then
    log "Stale boot lock detected - removing it and retrying."
    rmdir "$BOOT_LOCK" 2>/dev/null || true
    continue
  fi
  _lock_tries=$((_lock_tries + 1))
  if [ "$_lock_tries" -ge 180 ]; then
    log "ERROR: timed out waiting for the boot lock or ready marker."
    exit 1
  fi
  sleep 5
done

if [ "$_have_lock" = "1" ]; then
  trap 'rmdir "$BOOT_LOCK" 2>/dev/null || true' EXIT
  trap 'rmdir "$BOOT_LOCK" 2>/dev/null || true; exit 143' TERM INT

  mkdir -p "$SESSION_DIR"
  chown www-data:www-data "$SESSION_DIR" 2>/dev/null || true

  if [ -x "$ORIG_ENTRYPOINT" ]; then
    log "Running image entrypoint init via $ORIG_ENTRYPOINT"
    _init_rc=0
    _init_trace="/tmp/espocrm-init-trace.log"
    bash -x "$ORIG_ENTRYPOINT" /bin/true 2>"$_init_trace" || _init_rc=$?
    grep -E '^(info|warning|error):' "$_init_trace" >&2 || true
    if [ "$_init_rc" -ne 0 ]; then
      log "ERROR: image entrypoint init failed (rc=$_init_rc); last trace lines:"
      tail -n 40 "$_init_trace" >&2 || true
      log "----- data/logs (newest) -----"
      _newest_log=$(find "${APP_DIR}/data/logs/" -maxdepth 1 -name '*.log' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n 1 | cut -d' ' -f2-)
      if [ -n "$_newest_log" ]; then
        tail -n 60 "$_newest_log" >&2 || true
      else
        log "(no app log found)"
      fi
      exit "$_init_rc"
    fi
  else
    log "ERROR: image entrypoint not found at $ORIG_ENTRYPOINT; an image bump moved it and upgrades/config seeding would silently stop."
    exit 1
  fi

  if [ ! -f "${APP_DIR}/bootstrap.php" ]; then
    log "ERROR: ${APP_DIR}/bootstrap.php is missing after the image entrypoint ran."
    exit 1
  fi

  log "Applying runtime flags via seed_config.php..."
  if ! php "${SEED_CONFIG_SCRIPT}"; then
    log "ERROR: seed_config.php execution failed"
    exit 1
  fi

  if php "${APP_DIR}/clear_cache.php" 2>/dev/null; then
    log "Cache cleared successfully."
  else
    log "WARN: Cache clearing skipped or failed (non-critical)."
  fi

  chown -R www-data:www-data \
    "${APP_DIR}/data" "${APP_DIR}/custom" "${APP_DIR}/client/custom" 2>/dev/null || true

  touch "$READY_MARKER"
  rmdir "$BOOT_LOCK" 2>/dev/null || true
  trap - EXIT TERM INT
else
  log "Init done by another replica - skipping image init and seed."
  if [ ! -f "${APP_DIR}/bootstrap.php" ]; then
    log "ERROR: ${APP_DIR}/bootstrap.php is missing despite the ready marker."
    exit 1
  fi
fi

mkdir -p "$SESSION_DIR"
chown www-data:www-data "$SESSION_DIR" 2>/dev/null || true

if [ "$#" -gt 0 ]; then
  log "Exec CMD: $*"
  exec "$@"
fi

for cmd in apache2-foreground httpd-foreground php-fpm php-fpm8.3 php-fpm8.2 supervisord; do
  if command -v "$cmd" >/dev/null 2>&1; then
    log "Starting: $cmd"
    case "$cmd" in
      php-fpm|php-fpm8.*) exec "$cmd" -F ;;
      supervisord)        exec "$cmd" -n ;;
      *)                  exec "$cmd" ;;
    esac
  fi
done

log "No known server command found; tailing to keep container alive."
exec tail -f /dev/null
