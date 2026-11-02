#!/usr/bin/env bash
set -euo pipefail

: "${LDAP_HEALTHCHECK_REQUIRE_MEMBEROF:=false}"
: "${LDAP_PORT:?LDAP_PORT required}"

ldapsearch -x -H "ldap://127.0.0.1:${LDAP_PORT}" -s base -b "" "(objectClass=*)" dn >/dev/null 2>&1

if [ "${LDAP_HEALTHCHECK_REQUIRE_MEMBEROF}" = "true" ]; then
  ldapsearch -Q -Y EXTERNAL -H ldapi:/// -LLL \
    -b "cn=config" "(&(objectClass=olcOverlayConfig)(olcOverlay=memberof))" dn \
    | grep -q "^dn:"
fi
