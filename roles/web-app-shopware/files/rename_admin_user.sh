#!/usr/bin/env sh
#
# Rename the default Shopware admin user. Runs INSIDE the Shopware web
# container (piped via `container exec -i ... sh < this-file`).
# Required env, supplied via `container exec -e KEY=VALUE`:
#   SHOPWARE_ROOT  absolute path to the Shopware install
#   NEW_USER       target username for the renamed admin
set -e
cd "$SHOPWARE_ROOT"
old_user="admin"
if php bin/console user:list | grep -q "^$old_user "; then
  echo "[INFO] Renaming Shopware user: $old_user -> $NEW_USER"
  php bin/console user:update "$old_user" --username="$NEW_USER" || true
else
  echo "[INFO] No user named $old_user found (already renamed or custom setup)"
fi
