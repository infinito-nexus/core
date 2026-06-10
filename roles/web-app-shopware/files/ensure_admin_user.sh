#!/usr/bin/env sh
#
# Ensure the Shopware admin user exists with the desired credentials.
# Runs INSIDE the Shopware web container (piped via
# `container exec -i ... sh < this-file`).
#
# Required env, supplied via `container exec -e KEY=VALUE`:
#   SHOPWARE_ROOT     absolute path to the Shopware install
#   ADMIN_USER        username of the admin user
#   ADMIN_PASSWORD    password to set/enforce
#   ADMIN_FIRST_NAME  firstName attribute for user:create
#   ADMIN_LAST_NAME   lastName attribute for user:create
#   ADMIN_EMAIL       email attribute for user:create / user:update
set -e
cd "$SHOPWARE_ROOT"
php bin/console user:create "$ADMIN_USER" \
  --admin \
  --password="$ADMIN_PASSWORD" \
  --firstName="$ADMIN_FIRST_NAME" \
  --lastName="$ADMIN_LAST_NAME" \
  --email="$ADMIN_EMAIL" || true
php bin/console user:change-password "$ADMIN_USER" \
  --password="$ADMIN_PASSWORD" || true
php bin/console user:update "$ADMIN_USER" \
  --email="$ADMIN_EMAIL" 2>/dev/null || true
