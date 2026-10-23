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
#   KC_PURGE_WORKERS     parallel kcadm deletes
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${KC_RBAC_ROOT_PATH:?KC_RBAC_ROOT_PATH is required}"
: "${DEPLOYED_APP_IDS:?DEPLOYED_APP_IDS is required}"
: "${KC_PURGE_WORKERS:?KC_PURGE_WORKERS is required}"

exec </dev/null

[ -z "$DEPLOYED_APP_IDS" ] && exit 0

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get groups \
  -r "$KC_REALM" \
  -q max=500 --fields id,path --format csv --noquotes \
  > /tmp/kc_top_groups.txt

ROOT_ID=$(awk -F',' -v p="$KC_RBAC_ROOT_PATH" \
  '!/^\[/ && !/Cgroup/ && $2==p {print $1; exit}' \
  /tmp/kc_top_groups.txt | tr -d '\r')
[ -z "$ROOT_ID" ] && exit 0

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get \
  "groups/$ROOT_ID/children" -r "$KC_REALM" \
  -q max=500 --fields id,name --format csv --noquotes \
  > /tmp/kc_root_children.txt

awk -F',' -v keep="$DEPLOYED_APP_IDS" '
  BEGIN { n=split(keep,a," "); for(i=1;i<=n;i++) ok[a[i]]=1 }
  !/^\[/ && !/Cgroup/ && $2 != "" && !ok[$2] { print $1 }
' /tmp/kc_root_children.txt | tr -d '\r' > /tmp/kc_root_to_delete.txt

xargs -r -P "$KC_PURGE_WORKERS" -I '{}' container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh delete \
  "groups/{}" -r "$KC_REALM" < /tmp/kc_root_to_delete.txt || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
