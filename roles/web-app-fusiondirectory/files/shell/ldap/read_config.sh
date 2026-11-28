#!/usr/bin/env bash
#
# Output: one "<attribute>: <value>" line per attribute of FD_READ_ATTRIBUTES the
#   FusionDirectory configuration entry holds; nothing before the bootstrap created it.
#
# Required env, supplied via `container exec -e KEY`:
#   FD_READ_ATTRIBUTES  space-separated attributes of the configuration entry to read
# Required env, set by the container's env file:
#   LDAP01_HOST, LDAP01_PORT, LDAP01_BASE_DN, LDAP01_ADMIN_DN, LDAP01_ADMIN_PASS
set -uo pipefail

read -r -a attributes <<<"$FD_READ_ATTRIBUTES"
held="$(ldapsearch -x -LLL -o ldif-wrap=no -H "ldap://${LDAP01_HOST}:${LDAP01_PORT}" \
  -D "$LDAP01_ADMIN_DN" -y <(printf %s "$LDAP01_ADMIN_PASS") \
  -b "cn=config,ou=fusiondirectory,${LDAP01_BASE_DN}" -s base "(objectClass=*)" "${attributes[@]}")"
status=$?
if [ "$status" -eq 32 ]; then
  exit 0
fi
if [ "$status" -ne 0 ]; then
  exit "$status"
fi
for attribute in "${attributes[@]}"; do
  grep -E "^${attribute}: " <<<"$held"
  status=$?
  if [ "$status" -gt 1 ]; then
    exit "$status"
  fi
done
