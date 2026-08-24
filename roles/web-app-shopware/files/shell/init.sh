#!/bin/sh
# Shopware initialization script (POSIX sh)
# - Root phase: fix volumes & permissions, then switch to www-data
# - First run: perform system:install
# - Every run: run DB migrations + rebuild cache + compile assets & themes
# - Verifies admin bundles exist, otherwise exits with error

set -eu

APP_ROOT="/var/www/html"
MARKER="$APP_ROOT/.infinito/installed"
LOG_PREFIX="[INIT]"
PHP_BIN="php"

log() { printf "%s %s\n" "$LOG_PREFIX" "$1"; }
fail() { printf "%s [ERROR] %s\n" "$LOG_PREFIX" "$1" >&2; exit 1; }

retry() {
  _max="$1"; shift
  _n=1
  while true; do
    if "$@"; then return 0; fi
    if [ "$_n" -ge "$_max" ]; then fail "command failed after $_max attempts: $*"; fi
    log "attempt $_n/$_max failed, retrying in 5s: $*"
    _n=$((_n + 1))
    sleep 5
  done
}

if [ "$(id -u)" -eq 0 ]; then
  mkdir -p "$APP_ROOT/.infinito" \
           "$APP_ROOT/public/bundles" \
           "$APP_ROOT/public/media" \
           "$APP_ROOT/public/theme" \
           "$APP_ROOT/public/thumbnail" \
           "$APP_ROOT/public/sitemap" \
           "$APP_ROOT/var"

  log "Fixing permissions on shared volumes..."
  chown -R www-data:www-data \
    "$APP_ROOT/public" \
    "$APP_ROOT/var" \
    "$APP_ROOT/.infinito" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  chmod -R 775 \
    "$APP_ROOT/public" \
    "$APP_ROOT/var" \
    "$APP_ROOT/.infinito" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

  exec su -s /bin/sh www-data "$0" "$@"
fi

cd "$APP_ROOT" || fail "Cannot cd to $APP_ROOT"

APP_ENV_STR=$($PHP_BIN -r 'echo getenv("APP_ENV") ?: "";' 2>/dev/null || true)
APP_URL_STR=$($PHP_BIN -r 'echo getenv("APP_URL") ?: "";' 2>/dev/null || true)
[ -n "$APP_ENV_STR" ] || log "APP_ENV not set (using defaults)"
[ -n "$APP_URL_STR" ] || log "APP_URL not set (reverse proxy must set headers)"

log "Checking database via PDO..."
# shellcheck disable=SC2016
$PHP_BIN -r '
$url = getenv("DATABASE_URL");
if (!$url) { fwrite(STDERR, "DATABASE_URL not set\n"); exit(1); }
$p = parse_url($url);
if (!$p || !isset($p["scheme"])) { fwrite(STDERR, "Invalid DATABASE_URL\n"); exit(1); }
$host = $p["host"] ?? "localhost";
$port = $p["port"] ?? 3306;
$db   = ltrim($p["path"] ?? "", "/");
$user = $p["user"] ?? "";
$pass = $p["pass"] ?? "";
$dsn  = "mysql:host=".$host.";port=".$port.";dbname=".$db.";charset=utf8mb4";
$retries = 60;
while ($retries-- > 0) {
  try { new PDO($dsn, $user, $pass, [PDO::ATTR_TIMEOUT => 3]); exit(0); }
  catch (Exception $e) { sleep(2); }
}
fwrite(STDERR, "DB not reachable\n"); exit(1);
' || fail "Database not reachable"

FIRST_INSTALL=0
if [ ! -f "$MARKER" ]; then
  log "Checking if database is empty..."
  # shellcheck disable=SC2016
  if $PHP_BIN -r '
    $url = getenv("DATABASE_URL");
    $p   = parse_url($url);
    $db  = ltrim($p["path"] ?? "", "/");
    $dsn = "mysql:host=".($p["host"]??"localhost").";port=".($p["port"]??3306).";dbname=".$db.";charset=utf8mb4";
    $pdo = new PDO($dsn, $p["user"] ?? "", $p["pass"] ?? "");
    $q = $pdo->query("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=".$pdo->quote($db));
    $cnt = (int)$q->fetchColumn();
    exit($cnt === 0 ? 0 : 100);
  '; then
    FIRST_INSTALL=1
  else
    ST=$?
    if [ "$ST" -eq 100 ]; then
      log "Database not empty → skipping install"
    else
      fail "Database check failed (exit code $ST)"
    fi
  fi
fi

if [ "$FIRST_INSTALL" -eq 1 ]; then
  log "Performing first-time Shopware installation..."
  $PHP_BIN -d memory_limit=1024M bin/console system:install --basic-setup --create-database
  log "Locking the 'admin' account that --basic-setup creates with the published default password..."
  DEFAULT_ADMIN_PASSWORD="$($PHP_BIN -r 'echo bin2hex(random_bytes(32));')"
  $PHP_BIN -d memory_limit=1024M bin/console user:change-password admin \
    --password="$DEFAULT_ADMIN_PASSWORD"
  mkdir -p "$(dirname "$MARKER")"
  : > "$MARKER"
fi

log "Running database migrations..."
$PHP_BIN -d memory_limit=1024M bin/console database:migrate --all
$PHP_BIN -d memory_limit=1024M bin/console database:migrate-destructive --all

log "Rebuilding caches and assets..."
$PHP_BIN bin/console cache:clear
retry 5 $PHP_BIN bin/console bundle:dump
retry 5 $PHP_BIN bin/console assets:install --no-interaction --force
retry 5 $PHP_BIN bin/console theme:refresh
retry 5 $PHP_BIN bin/console theme:compile
$PHP_BIN bin/console dal:refresh:index || log "dal:refresh:index failed (non-critical)"

if [ ! -d "public/bundles/administration" ]; then
  fail "Missing directory public/bundles/administration (asset build failed)"
fi
if ! ls public/bundles/administration/* >/dev/null 2>&1; then
  fail "No files found in public/bundles/administration (asset build failed)"
fi

$PHP_BIN bin/console system:version 2>/dev/null || log "system:version not available"

log "Initialization complete."
