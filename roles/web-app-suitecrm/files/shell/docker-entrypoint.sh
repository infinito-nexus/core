#!/bin/sh
set -eu

APP_DIR="${SUITECRM_APP_DIR:?SUITECRM_APP_DIR must be baked into the image}"
WEB_USER="${SUITECRM_WEB_USER:?SUITECRM_WEB_USER must be baked into the image}"
WEB_GROUP="${SUITECRM_WEB_GROUP:?SUITECRM_WEB_GROUP must be baked into the image}"
INSTALL_FLAG="${APP_DIR}/public/installed.flag"
SEED_DIR="${SUITECRM_SEED_DIR:?SUITECRM_SEED_DIR must be baked into the image}"
APP_VERSION="${SUITECRM_APP_VERSION:?SUITECRM_APP_VERSION must be baked into the image}"
SEED_STAMP="${APP_DIR}/.tree-seeded"
TREE_VERSION_FILE="${APP_DIR}/VERSION"
UPGRADE_DIR="${APP_DIR}/tmp/package/upgrade"
UPGRADE_PACKAGE="SuiteCRM-${APP_VERSION}"

log() { printf '%s %s\n' "[suitecrm-entrypoint]" "$*" >&2; }

version_lt() {
  [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n 1)" = "$1" ]
}

upgrade_tree() {
  log "Upgrading the SuiteCRM tree from $1 to ${APP_VERSION}..."
  rm -rf "$UPGRADE_DIR"
  mkdir -p "$UPGRADE_DIR"
  (cd "$SEED_DIR" && zip -q -r -0 "${UPGRADE_DIR}/${UPGRADE_PACKAGE}.zip" .)
  php bin/console suitecrm:app:upgrade -n -t "$UPGRADE_PACKAGE"
  echo "installed" > "$INSTALL_FLAG"
  php bin/console suitecrm:app:upgrade-finalize -n -t "$UPGRADE_PACKAGE" -m keep
  rm -rf "$UPGRADE_DIR"
  find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name extensions -exec chown -R "$WEB_USER:$WEB_GROUP" {} +
  log "SuiteCRM tree upgraded to $(cat "$TREE_VERSION_FILE")."
}

if [ ! -d "$APP_DIR" ]; then
  log "ERROR: Application directory '$APP_DIR' does not exist."
  exit 1
fi

if [ -n "${SUITECRM_SAML_IDP_DESCRIPTOR_URL:-}" ]; then
  log "Fetching the IdP signing certificate from ${SUITECRM_SAML_IDP_DESCRIPTOR_URL}..."
  _descriptor=$(curl -fsS --connect-timeout 20 --max-time 25 --retry 20 --retry-all-errors --retry-delay 5 --proxy "${SUITECRM_OIDC_SOCKS_PROXY:-}" "$SUITECRM_SAML_IDP_DESCRIPTOR_URL")
  _tags=$(printf '%s' "$_descriptor" | tr '<' '\n')
  SAML_IDP_X509CERT=$(printf '%s' "$_tags" | awk -F'>' '/KeyDescriptor[^>]*use="signing"/ { s=1 } s && $1 ~ /X509Certificate$/ && $2 != "" { print $2; exit }')
  if [ -z "$SAML_IDP_X509CERT" ]; then
    SAML_IDP_X509CERT=$(printf '%s' "$_tags" | awk -F'>' '$1 ~ /X509Certificate$/ && $2 != "" { print $2; exit }')
  fi
  if [ -z "$SAML_IDP_X509CERT" ]; then
    log "ERROR: no X509Certificate in the IdP descriptor."
    exit 1
  fi
  export SAML_IDP_X509CERT
  log "IdP certificate loaded."
fi

TMPDIR="${APP_DIR}/tmp"
export TMPDIR
mkdir -p "$TMPDIR"
chown "$WEB_USER:$WEB_GROUP" "$TMPDIR"
chmod 775 "$TMPDIR"

BOOT_LOCK="${TMPDIR}/.suitecrm-boot.lock.d"

_have_lock=0
_lock_tries=0
while :; do
  if mkdir "$BOOT_LOCK" 2>/dev/null; then
    _have_lock=1
    break
  fi
  _lock_mtime=$(stat -c %Y "$BOOT_LOCK" 2>/dev/null || echo 0)
  if [ "$_lock_mtime" -gt 0 ] && [ $(($(date +%s) - _lock_mtime)) -ge 1800 ]; then
    log "Stale boot lock detected - removing it and retrying."
    rmdir "$BOOT_LOCK" 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  fi
  if [ -f "$INSTALL_FLAG" ]; then
    break
  fi
  _lock_tries=$((_lock_tries + 1))
  if [ "$_lock_tries" -ge 420 ]; then
    log "ERROR: timed out waiting for the boot lock or install flag."
    exit 1
  fi
  sleep 5
done

if [ "$_have_lock" = "1" ]; then
  trap 'rmdir "$BOOT_LOCK" 2>/dev/null || true' EXIT
  trap 'rmdir "$BOOT_LOCK" 2>/dev/null || true; exit 143' TERM INT  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

  CACHE_REFRESH=0
  if [ -d "$UPGRADE_DIR" ] || [ -f "$INSTALL_FLAG" ]; then
    _tree_version=$(cat "$TREE_VERSION_FILE")
    if version_lt "$APP_VERSION" "$_tree_version"; then
      log "ERROR: volume tree is ${_tree_version}, newer than the image's ${APP_VERSION}; SuiteCRM cannot downgrade, pin ${_tree_version} or later."
      exit 1
    fi
    if [ -d "$UPGRADE_DIR" ] || [ "$_tree_version" != "$APP_VERSION" ]; then
      upgrade_tree "$_tree_version"
      CACHE_REFRESH=1
    fi
  elif [ ! -f "$SEED_STAMP" ]; then
    log "Seeding SuiteCRM tree from ${SEED_DIR} into ${APP_DIR}..."
    cp -a "${SEED_DIR}/." "${APP_DIR}/"
    log "Seed complete."
  fi
  cat "$TREE_VERSION_FILE" > "$SEED_STAMP"
  chown "$WEB_USER:$WEB_GROUP" "$SEED_STAMP"

  if [ ! -f "$INSTALL_FLAG" ]; then
    CACHE_REFRESH=1
    log "SuiteCRM 8 is not installed - performing automated installation..."

    php bin/console suitecrm:app:install \
        -u "$SUITECRM_ADMIN_USERNAME" \
        -p "$SUITECRM_ADMIN_PASSWORD" \
        -U "$SUITECRM_DB_USER" \
        -P "$SUITECRM_DB_PASSWORD" \
        -H "$SUITECRM_DB_HOST" \
        -Z "$SUITECRM_DB_PORT" \
        -N "$SUITECRM_DB_NAME" \
        -S "$SUITECRM_URL" \
        -d "no"

    echo "installed" > "$INSTALL_FLAG"
    chown "$WEB_USER:$WEB_GROUP" "$INSTALL_FLAG"

    log "SuiteCRM installation completed successfully."
  else
    log "SuiteCRM already installed - skipping installer."
  fi

  if [ -d "${APP_DIR}/cache/prod" ] && [ -n "$(find "${APP_DIR}/extensions" \( -path '*/config/*' -o -path '*/backend/*' \) -type f -newer "${APP_DIR}/cache/prod" -print -quit)" ]; then
    CACHE_REFRESH=1
    log "Extension config or backend code is newer than the prod cache - refreshing it."
  fi

  if [ "$CACHE_REFRESH" = "1" ] || [ ! -d "${APP_DIR}/cache/prod" ]; then
    log "Clearing Symfony cache..."
    php bin/console cache:clear --no-warmup || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
    php bin/console cache:warmup || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  else
    log "Existing prod cache - skipping cache:clear/warmup."
  fi

  if [ "$CACHE_REFRESH" = "1" ]; then
    chown -R "$WEB_USER:$WEB_GROUP" "${APP_DIR}/public/legacy"
  fi

  chown -R "$WEB_USER:$WEB_GROUP" "${APP_DIR}/cache" "${APP_DIR}/public/legacy/cache" 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

  chown -R "$WEB_USER:$WEB_GROUP" "${APP_DIR}/logs"

  rmdir "$BOOT_LOCK" 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  trap - EXIT TERM INT
else
  log "SuiteCRM installed by another replica - skipping installer and cache pass."
fi

log "Starting $*..."
exec "$@"
