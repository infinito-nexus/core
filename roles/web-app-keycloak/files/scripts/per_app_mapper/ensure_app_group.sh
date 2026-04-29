#!/bin/bash
# Ensure /<KC_RBAC_ROOT_PATH>/<APP_ID> Keycloak group exists. Echoes
# its id on stdout (existing or freshly created).
#
# Required env:
#   KC_CONTAINER         keycloak container name
#   KC_REALM             realm name
#   APP_ID               application id (e.g. web-app-wordpress)
#   ROOT_GROUP_ID        Keycloak group id of the RBAC root container
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${APP_ID:?APP_ID is required}"
: "${ROOT_GROUP_ID:?ROOT_GROUP_ID is required}"

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get \
  "groups/$ROOT_GROUP_ID/children" -r "$KC_REALM" \
  -q max=500 --fields id,name --format csv --noquotes 2>/dev/null \
  > /tmp/kc_children_listing.txt

EXISTING=$(awk -F',' -v n="$APP_ID" \
  '!/^\[/ && !/Cgroup/ && $2==n {print $1; exit}' \
  /tmp/kc_children_listing.txt | tr -d '\r')

if [ -n "$EXISTING" ]; then
  printf '%s\n' "$EXISTING"
  exit 0
fi

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh create \
  "groups/$ROOT_GROUP_ID/children" -r "$KC_REALM" -s "name=$APP_ID" -i 2>/dev/null \
  > /tmp/kc_create_output.txt

grep -vE '(^\[|Cgroup)' /tmp/kc_create_output.txt \
  | grep -E '^[0-9a-fA-F-]{8,}$' | head -1 | tr -d '\r'
