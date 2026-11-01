#!/bin/sh
# Usage:
#   Piped into the `sh -s` of a one-off MediaWiki container, no arguments.
#
#   MEDIAWIKI_HTML_DIR        wiki root that holds maintenance/run.php
#   MEDIAWIKI_ADMIN_NAME      account to create, promote and realign
#   MEDIAWIKI_ADMIN_PASSWORD  password it must accept afterwards
#   MEDIAWIKI_ADMIN_EMAIL     email an account created here gets
#   MEDIAWIKI_LOCAL_LOGIN     "true" while a local password provider is loaded
#   MEDIAWIKI_ADMIN_STATE_SQL files/sql/admin_state.sql; %(name)s and %(email)s become hex literals
#
# A missing account is created only while local login is on; SSO-only, createAndPromote would
# fail on the password step, so SSO's first login creates it, named after Keycloak's
# preferred_username.
#
# Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
set -eu

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

hex() {
  printf '%s' "$1" | od -An -v -tx1 | tr -d ' \n'
}

if [ -z "${MEDIAWIKI_HTML_DIR:-}" ] || [ -z "${MEDIAWIKI_ADMIN_NAME:-}" ] || [ -z "${MEDIAWIKI_ADMIN_EMAIL:-}" ]; then
  fail "MEDIAWIKI_HTML_DIR, MEDIAWIKI_ADMIN_NAME or MEDIAWIKI_ADMIN_EMAIL is empty."
fi

if [ -z "${MEDIAWIKI_ADMIN_STATE_SQL:-}" ]; then
  fail "MEDIAWIKI_ADMIN_STATE_SQL is empty."
fi

run="${MEDIAWIKI_HTML_DIR}/maintenance/run.php"
query="$(printf '%s\n' "$MEDIAWIKI_ADMIN_STATE_SQL" | sed \
  -e "s/%(name)s/X'$(hex "$MEDIAWIKI_ADMIN_NAME")'/g" \
  -e "s/%(email)s/X'$(hex "$MEDIAWIKI_ADMIN_EMAIL")'/g")"

if ! probe="$(php "$run" sql --query "$query" 2>&1)"; then
  fail "the account probe exited non-zero: ${probe}"
fi
state="$(printf '%s\n' "$probe" | sed -n 's/^ *\[state\] => //p')"

case "$state" in
admin) ;;
absent)
  if [ "${MEDIAWIKI_LOCAL_LOGIN:-}" != "true" ]; then
    echo "[UNCHANGED] ${MEDIAWIKI_ADMIN_NAME} is provisioned by SSO at first login"
    exit 0
  fi
  if [ -z "${MEDIAWIKI_ADMIN_PASSWORD:-}" ]; then
    fail "MEDIAWIKI_ADMIN_PASSWORD is empty; refusing to create ${MEDIAWIKI_ADMIN_NAME} without it."
  fi
  if ! out="$(php "$run" createAndPromote --bureaucrat --sysop --email "$MEDIAWIKI_ADMIN_EMAIL" "$MEDIAWIKI_ADMIN_NAME" "$MEDIAWIKI_ADMIN_PASSWORD" 2>&1)"; then
    fail "createAndPromote exited non-zero: ${out}"
  fi
  case "$out" in
  *"Creating and promoting User:"*)
    echo "[CHANGED] the MediaWiki administrator ${MEDIAWIKI_ADMIN_NAME} was created with the declared password"
    exit 0
    ;;
  *) fail "createAndPromote did not create ${MEDIAWIKI_ADMIN_NAME}: ${out}" ;;
  esac
  ;;
not-admin:*)
  if [ "${MEDIAWIKI_LOCAL_LOGIN:-}" = "true" ]; then
    reason="local login is on"
  elif [ "$state" = "not-admin:mismatch" ]; then
    reason="its email differs from ${MEDIAWIKI_ADMIN_EMAIL}"
  elif [ "$state" = "not-admin:unconfirmed" ]; then
    reason="its email ${MEDIAWIKI_ADMIN_EMAIL} is not confirmed"
  else
    if ! out="$(php "$run" createAndPromote --force --bureaucrat --sysop "$MEDIAWIKI_ADMIN_NAME" 2>&1)"; then
      fail "createAndPromote exited non-zero: ${out}"
    fi
    case "$out" in
    *"Promoting User:"*)
      echo "[CHANGED] promoted ${MEDIAWIKI_ADMIN_NAME} (SSO account, email matches)"
      exit 0
      ;;
    *) fail "createAndPromote did not promote ${MEDIAWIKI_ADMIN_NAME}: ${out}" ;;
    esac
  fi
  fail "the MediaWiki account ${MEDIAWIKI_ADMIN_NAME} is no sysop and is not promoted (${reason}); add it to the sysop group or rename it, then redeploy"
  ;;
no-admin) fail "MediaWiki has no sysop, so its install is unfinished; finish or reset that install instead of adding ${MEDIAWIKI_ADMIN_NAME} to it" ;;
email-held:*) fail "the email ${MEDIAWIKI_ADMIN_EMAIL} is held by the MediaWiki account ${state#email-held:}; change that account's email, then redeploy" ;;
*) fail "the account probe returned no state: ${probe}" ;;
esac

set -- --force --bureaucrat --sysop "$MEDIAWIKI_ADMIN_NAME"

if [ "${MEDIAWIKI_LOCAL_LOGIN:-}" = "true" ]; then
  if [ -z "${MEDIAWIKI_ADMIN_PASSWORD:-}" ]; then
    fail "MEDIAWIKI_ADMIN_PASSWORD is empty; refusing to set it."
  fi
  set -- "$@" "$MEDIAWIKI_ADMIN_PASSWORD"
fi

if ! out="$(php "$run" createAndPromote "$@" 2>&1)"; then
  fail "createAndPromote exited non-zero: ${out}"
fi

case "$out" in
*"Password set."*)
  echo "[CHANGED] the MediaWiki administrator accepts the declared password"
  ;;
*"Promoting User:"*)
  echo "[CHANGED] the MediaWiki administrator was promoted"
  ;;
*"Account exists and nothing to do."*)
  echo "[UNCHANGED] the MediaWiki administrator is already in place"
  ;;
*)
  fail "createAndPromote neither created nor realigned: ${out}"
  ;;
esac
