#!/bin/bash
# Resolve the Keycloak group id for the RBAC root path (e.g. /roles).
# Echoes the id on stdout; empty when the path has no group; exits
# non-zero when the groups listing itself cannot be fetched.
#
# Required env:
#   KC_CONTAINER         keycloak container name
#   KC_REALM             realm name
#   KC_RBAC_ROOT_PATH    e.g. /roles
set -eo pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${KC_RBAC_ROOT_PATH:?KC_RBAC_ROOT_PATH is required}"

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get groups \
  -r "$KC_REALM" \
  -q max=500 --fields id,path --format csv --noquotes \
  > /tmp/kc_groups_top.txt

awk -F',' -v p="$KC_RBAC_ROOT_PATH" \
  '!/^\[/ && !/Cgroup/ && $2==p {print $1; exit}' \
  /tmp/kc_groups_top.txt | tr -d '\r'
