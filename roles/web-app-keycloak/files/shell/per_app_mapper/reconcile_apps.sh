#!/bin/bash
# Required env:
#   KC_CONTAINER          keycloak container name
#   KC_REALM              realm name
#   LDAP_COMPONENT_ID     Keycloak LDAP component id (mapper parentId)
#   ROOT_GROUP_ID         Keycloak group id of the RBAC root container
#   PAYLOADS_FILE         host-side file, one `<app_id> <mapper_name> <base64 mapper JSON>` line per app
#   GROUP_ID_PLACEHOLDER  token in the mapper JSON that stands for the app group id
#   KC_WORKERS            apps reconciled in parallel
#   KC_SYNC_ATTEMPTS      mapper sync attempts per app
#   KC_SYNC_DELAY         seconds between two sync attempts
#   KC_SYNC_TIMEOUT       seconds one sync attempt may take
#
# Output: one `<step>-failed <app_id>` line per app that failed.
# Exit: 0 every app reconciled, 2 only mapper syncs failed, 1 otherwise.
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${LDAP_COMPONENT_ID:?LDAP_COMPONENT_ID is required}"
: "${ROOT_GROUP_ID:?ROOT_GROUP_ID is required}"
: "${PAYLOADS_FILE:?PAYLOADS_FILE is required}"
: "${GROUP_ID_PLACEHOLDER:?GROUP_ID_PLACEHOLDER is required}"
: "${KC_WORKERS:?KC_WORKERS is required}"
: "${KC_SYNC_ATTEMPTS:?KC_SYNC_ATTEMPTS is required}"
: "${KC_SYNC_DELAY:?KC_SYNC_DELAY is required}"
: "${KC_SYNC_TIMEOUT:?KC_SYNC_TIMEOUT is required}"
[ -r "$PAYLOADS_FILE" ] || { echo "PAYLOADS_FILE not readable: $PAYLOADS_FILE" >&2; exit 1; }
awk 'NF != 3 { bad = 1 } END { exit bad }' "$PAYLOADS_FILE" \
  || { echo "PAYLOADS_FILE has a line without exactly 3 fields: $PAYLOADS_FILE" >&2; exit 1; }

KCADM=/opt/keycloak/bin/kcadm.sh
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export KCADM work

if ! container exec -i "$KC_CONTAINER" "$KCADM" get "groups/$ROOT_GROUP_ID/children" \
  -r "$KC_REALM" -q max=500 --fields id,name --format csv --noquotes \
  </dev/null >"$work/groups.csv"; then
  echo "listing-failed groups/$ROOT_GROUP_ID/children"
  exit 1
fi

if ! container exec -i "$KC_CONTAINER" "$KCADM" get components -r "$KC_REALM" \
  -q "parentId=$LDAP_COMPONENT_ID" -q providerId=group-ldap-mapper \
  -q max=500 --fields id,name --format csv --noquotes \
  </dev/null >"$work/mappers.csv"; then
  echo "listing-failed components"
  exit 1
fi

# shellcheck disable=SC2329,SC2317  # invoked indirectly through reconcile_steps
kcw() {
  container exec -i "$KC_CONTAINER" "$KCADM" "$@" --config "$cfg"
}

# Args: app_id, mapper_name, base64 mapper JSON. Sets failed_step on failure.
# shellcheck disable=SC2329,SC2317  # invoked indirectly through reconcile_app
reconcile_steps() {
  local app="$1" mapper_name="$2" payload_b64="$3"
  local payload="$work/$1.json" group_id mapper_id stale_id attempt=1

  group_id="$(awk -F',' -v n="$app" '!/^\[/ && !/Cgroup/ && $2==n {print $1; exit}' \
    "$work/groups.csv" | tr -d '\r')"
  if [ -z "$group_id" ]; then
    group_id="$(kcw create "groups/$ROOT_GROUP_ID/children" -r "$KC_REALM" -s "name=$app" -i \
      </dev/null | grep -vE '(^\[|Cgroup)' | grep -E '^[0-9a-fA-F-]{8,}$' | head -1 | tr -d '\r')"
  fi
  [ -n "$group_id" ] || { failed_step=ensure; return 1; }

  kcw get "groups/$group_id/children" -r "$KC_REALM" \
    -q max=500 --fields id,name --format csv --noquotes </dev/null \
    | awk -F',' '!/^\[/ && !/Cgroup/ && $1 != "" { print $1 }' \
    | tr -d '\r' >"$work/$app.children"
  while IFS= read -r stale_id; do
    [ -z "$stale_id" ] && continue
    kcw delete "groups/$stale_id" -r "$KC_REALM" </dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  done <"$work/$app.children"

  printf '%s' "$payload_b64" | base64 -d \
    | sed "s|$GROUP_ID_PLACEHOLDER|$group_id|g" >"$payload" \
    || { failed_step=render; return 1; }

  mapper_id="$(awk -F',' -v n="$mapper_name" '!/^\[/ && !/Cgroup/ && $2==n {print $1; exit}' \
    "$work/mappers.csv" | tr -d '\r')"
  if [ -n "$mapper_id" ]; then
    sed "s|\"name\":|\"id\": \"$mapper_id\",\n    \"name\":|" "$payload" \
      | kcw update "components/$mapper_id" -r "$KC_REALM" -f - \
      >/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  else
    mapper_id="$(kcw create components -r "$KC_REALM" -f - -i <"$payload" \
      | grep -vE '(^\[|Cgroup)' | grep -E '^[0-9a-fA-F-]{8,}$' | head -1 | tr -d '\r')"
  fi
  [ -n "$mapper_id" ] || { failed_step=upsert; return 1; }

  until timeout "$KC_SYNC_TIMEOUT" container exec -i "$KC_CONTAINER" "$KCADM" create \
    "user-storage/$LDAP_COMPONENT_ID/mappers/$mapper_id/sync?direction=fedToKeycloak" \
    -r "$KC_REALM" --config "$cfg" </dev/null >"$work/$app.sync" 2>&1; do
    if [ "$attempt" -ge "$KC_SYNC_ATTEMPTS" ]; then
      sed "s|^|$app sync: |" "$work/$app.sync" >&2
      failed_step=sync
      return 1
    fi
    attempt=$((attempt + 1))
    sleep "$KC_SYNC_DELAY"
  done
}

# Args: app_id, mapper_name, base64 mapper JSON. Leaves `<app_id>.done` or `<app_id>.failed` in $work.
# shellcheck disable=SC2329,SC2317  # invoked indirectly through xargs + bash -c
reconcile_app() {
  local app="$1" cfg="/tmp/kcadm-$1-$$.config" failed_step=""
  # shellcheck disable=SC2016  # $HOME and $1 expand in the container shell
  if container exec -i "$KC_CONTAINER" sh -c 'cp "$HOME/.keycloak/kcadm.config" "$1"' sh "$cfg" </dev/null; then
    reconcile_steps "$@"
    container exec -i "$KC_CONTAINER" rm -f "$cfg" </dev/null
  else
    failed_step=config
  fi
  if [ -n "$failed_step" ]; then
    printf '%s\n' "$failed_step" >"$work/$app.failed"
  else
    : >"$work/$app.done"
  fi
}
export -f kcw reconcile_steps reconcile_app

# shellcheck disable=SC2016  # the single-quoted body expands inside the child bash
xargs -r -n 3 -P "$KC_WORKERS" bash -c 'reconcile_app "$@"' _ <"$PAYLOADS_FILE"
xargs_rc=$?

hard=0
sync=0
while read -r app _ || [ -n "$app" ]; do
  [ -e "$work/$app.done" ] && continue
  step=incomplete
  [ -s "$work/$app.failed" ] && step="$(<"$work/$app.failed")"
  printf '%s-failed %s\n' "$step" "$app"
  if [ "$step" = sync ]; then sync=1; else hard=1; fi
done <"$PAYLOADS_FILE"

if [ "$xargs_rc" -ne 0 ]; then
  echo "xargs exited $xargs_rc" >&2
  hard=1
fi
[ "$hard" -eq 1 ] && exit 1
[ "$sync" -eq 1 ] && exit 2
exit 0
