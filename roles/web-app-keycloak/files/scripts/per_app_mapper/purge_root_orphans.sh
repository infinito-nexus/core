#!/bin/bash
# Sweep stale flat / orphan Keycloak groups directly under the RBAC
# root (e.g. /roles/<app>-<role> or /roles/<role-name> collisions
# from earlier mapper configurations). Children whose name is one of
# the deployed application IDs are kept; everything else is deleted
# so the next per-app mapper sync rebuilds a clean tree.
#
# Required env:
#   KC_CONTAINER         keycloak container name
#   KC_REALM             realm name
#   KC_RBAC_ROOT_PATH    e.g. /roles
#   DEPLOYED_APP_IDS     space-separated list of application IDs
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${KC_RBAC_ROOT_PATH:?KC_RBAC_ROOT_PATH is required}"
: "${DEPLOYED_APP_IDS:?DEPLOYED_APP_IDS is required}"

[ -z "$DEPLOYED_APP_IDS" ] && exit 0

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get groups \
  -r "$KC_REALM" \
  -q max=500 --fields id,path --format csv --noquotes 2>/dev/null \
  > /tmp/kc_top_groups.txt

ROOT_ID=$(awk -F',' -v p="$KC_RBAC_ROOT_PATH" \
  '!/^\[/ && !/Cgroup/ && $2==p {print $1; exit}' \
  /tmp/kc_top_groups.txt | tr -d '\r')
[ -z "$ROOT_ID" ] && exit 0

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get \
  "groups/$ROOT_ID/children" -r "$KC_REALM" \
  -q max=500 --fields id,name --format csv --noquotes 2>/dev/null \
  > /tmp/kc_root_children.txt

awk -F',' -v keep="$DEPLOYED_APP_IDS" '
  BEGIN { n=split(keep,a," "); for(i=1;i<=n;i++) ok[a[i]]=1 }
  !/^\[/ && !/Cgroup/ && $2 != "" && !ok[$2] { print $1 }
' /tmp/kc_root_children.txt | tr -d '\r' > /tmp/kc_root_to_delete.txt

while IFS= read -r stale_id; do
  [ -z "$stale_id" ] && continue
  container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh delete \
    "groups/$stale_id" -r "$KC_REALM" </dev/null 2>/dev/null || true
done < /tmp/kc_root_to_delete.txt
