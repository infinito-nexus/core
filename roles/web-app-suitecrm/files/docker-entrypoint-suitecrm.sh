#!/bin/sh
set -eu

APP_DIR="/var/www/html"
WEB_USER="www-data"
WEB_GROUP="www-data"
INSTALL_FLAG="${APP_DIR}/public/installed.flag"

log() { printf '%s %s\n' "[suitecrm-entrypoint]" "$*" >&2; }

############################################
# Sanity Checks
############################################
if [ ! -d "$APP_DIR" ]; then
  log "ERROR: Application directory '$APP_DIR' does not exist."
  exit 1
fi

############################################
# Permissions
############################################
log "Adjusting file permissions..."
chown -R "$WEB_USER:$WEB_GROUP" "$APP_DIR"
find "$APP_DIR" -type d -exec chmod 755 {} \;
find "$APP_DIR" -type f -exec chmod 644 {} \;

for d in cache public/upload public/legacy/upload public/legacy/cache; do
  if [ -d "${APP_DIR}/${d}" ]; then
    chmod -R 775 "${APP_DIR}/${d}"
    chown -R "$WEB_USER:$WEB_GROUP" "${APP_DIR}/${d}"
  fi
done

TMPDIR="${APP_DIR}/tmp"
export TMPDIR
mkdir -p "$TMPDIR"
chown -R "$WEB_USER:$WEB_GROUP" "$TMPDIR"
chmod 775 "$TMPDIR"

############################################
# Auto-Install SuiteCRM (only if not yet installed)
############################################
if [ ! -f "$INSTALL_FLAG" ]; then
  log "SuiteCRM 8 is not installed — performing automated installation..."

  # CLI installer (SuiteCRM 8)
  # Ref: ./bin/console suitecrm:app:install -u "admin" -p "pass" -U "db_user" -P "db_pass" -H "db_host" -N "db_name" -S "https://crm.example.com" -d "yes"
  php bin/console suitecrm:app:install \
      -u "$SUITECRM_ADMIN_USERNAME" \
      -p "$SUITECRM_ADMIN_PASSWORD" \
      -U "$SUITECRM_DB_USER" \
      -P "$SUITECRM_DB_PASSWORD" \
      -H "$SUITECRM_DB_HOST" \
      -N "$SUITECRM_DB_NAME" \
      -S "$SUITECRM_URL" \
      -d "no"

  # Mark as installed
  echo "installed" > "$INSTALL_FLAG"
  chown "$WEB_USER:$WEB_GROUP" "$INSTALL_FLAG"

  log "SuiteCRM installation completed successfully."
else
  log "SuiteCRM already installed — skipping installer."
fi

############################################
# Clear Symfony Cache
############################################
log "Clearing Symfony cache..."
php bin/console cache:clear --no-warmup || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
php bin/console cache:warmup || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

############################################
# Healthcheck file
############################################
echo "OK" > "${APP_DIR}/public/healthcheck.html"
chown "$WEB_USER:$WEB_GROUP" "${APP_DIR}/public/healthcheck.html"

############################################
# Start Apache
############################################
log "Starting apache2-foreground..."
exec apache2-foreground
