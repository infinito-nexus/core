#!/bin/sh
# Usage:
#   Piped into the `sh -s` of a one-off MediaWiki container, no arguments.
#
#   MEDIAWIKI_HTML_DIR        wiki root that holds maintenance/run.php
#   MEDIAWIKI_ADMIN_NAME      account to create, promote and realign
#   MEDIAWIKI_ADMIN_PASSWORD  password it must accept afterwards
#   MEDIAWIKI_LOCAL_LOGIN     "true" while a local password provider is loaded
#
# Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
set -eu

if [ -z "${MEDIAWIKI_HTML_DIR:-}" ] || [ -z "${MEDIAWIKI_ADMIN_NAME:-}" ]; then
  echo "[FAIL] MEDIAWIKI_HTML_DIR or MEDIAWIKI_ADMIN_NAME is empty." >&2
  exit 1
fi

set -- --force --bureaucrat --sysop "$MEDIAWIKI_ADMIN_NAME"

if [ "${MEDIAWIKI_LOCAL_LOGIN:-}" = "true" ]; then
  if [ -z "${MEDIAWIKI_ADMIN_PASSWORD:-}" ]; then
    echo "[FAIL] MEDIAWIKI_ADMIN_PASSWORD is empty; refusing to set it." >&2
    exit 1
  fi
  set -- "$@" "$MEDIAWIKI_ADMIN_PASSWORD"
fi

if ! out="$(php "${MEDIAWIKI_HTML_DIR}/maintenance/run.php" createAndPromote "$@" 2>&1)"; then
  echo "[FAIL] createAndPromote exited non-zero: ${out}" >&2
  exit 1
fi

case "$out" in
*"Password set."*)
  echo "[CHANGED] the MediaWiki administrator accepts the declared password"
  ;;
*"Creating and promoting User:"* | *"Promoting User:"*)
  echo "[CHANGED] the MediaWiki administrator was created or promoted"
  ;;
*"Account exists and nothing to do."*)
  echo "[UNCHANGED] the MediaWiki administrator is already in place"
  ;;
*)
  echo "[FAIL] createAndPromote neither created nor realigned: ${out}" >&2
  exit 1
  ;;
esac
