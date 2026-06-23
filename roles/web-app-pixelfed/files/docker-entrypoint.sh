#!/usr/bin/env bash
set -xeo pipefail

if [ -n "${FORCE_HTTPS:-}" ]; then
  sed -i 's#</VirtualHost#SetEnv HTTPS on\n</VirtualHost#' /etc/apache2/sites-enabled/000-default.conf
fi

cp -R storage.skel/* storage/
chown -R www-data:www-data storage/ bootstrap/

php /wait-for-db.php

if [ -n "${CA_TRUST_CERT:-}" ] && [ -r "${CA_TRUST_CERT}" ]; then
  if ! command -v update-ca-certificates >/dev/null 2>&1; then
    { apt-get update -y && apt-get install -y --no-install-recommends ca-certificates; } || true
  fi
  cp "${CA_TRUST_CERT}" "/usr/local/share/ca-certificates/${CA_TRUST_NAME}.crt" || true
  update-ca-certificates || true
fi

echo "++++ Start apache... ++++"
# shellcheck disable=SC1091
source /etc/apache2/envvars
exec dumb-init apache2 -DFOREGROUND
