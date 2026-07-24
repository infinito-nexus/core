#!/bin/bash
# Delete every subgroup under /<KC_RBAC_ROOT_PATH>/<APP_ID> so the next
# per-app mapper sync rebuilds the role-group children with the
# canonical description-based names.
#
# Required env:
#   KC_CONTAINER         keycloak container name
#   KC_REALM             realm name
#   APP_GROUP_ID         Keycloak group id of /<root>/<APP_ID>
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${APP_GROUP_ID:?APP_GROUP_ID is required}"

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get \
  "groups/$APP_GROUP_ID/children" -r "$KC_REALM" \
  -q max=500 --fields id,name --format csv --noquotes 2>/dev/null \
  > /tmp/kc_app_children.txt

awk -F',' '!/^\[/ && !/Cgroup/ && $1 != "" { print $1 }' \
  /tmp/kc_app_children.txt | tr -d '\r' > /tmp/kc_app_orphans.txt

while IFS= read -r stale_id; do
  [ -z "$stale_id" ] && continue
  container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh delete \
    "groups/$stale_id" -r "$KC_REALM" </dev/null 2>/dev/null || true
done < /tmp/kc_app_orphans.txt
