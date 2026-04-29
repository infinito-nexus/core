#!/bin/bash
# Create or update the per-application group-ldap-mapper named
# `ldap-roles-<APP_ID>`. Echoes the mapper id on stdout.
#
# The JSON payload is rendered ahead of this script by Ansible's
# `template:` module from
# `templates/import/components/ldap-roles-per-app-mapper.json.j2` so
# the mapper config stays a single SPOT alongside the other realm
# import templates.
#
# Required env:
#   KC_CONTAINER         keycloak container name
#   KC_REALM             realm name
#   LDAP_COMPONENT_ID    Keycloak LDAP component id (parentId)
#   MAPPER_NAME          mapper name (rendered by the `kc_per_app_mapper_name`
#                        Ansible filter, requirement-005 SPOT)
#   PAYLOAD_FILE         host-side path to the rendered mapper JSON
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${LDAP_COMPONENT_ID:?LDAP_COMPONENT_ID is required}"
: "${MAPPER_NAME:?MAPPER_NAME is required}"
: "${PAYLOAD_FILE:?PAYLOAD_FILE is required}"
[ -r "$PAYLOAD_FILE" ] || { echo "PAYLOAD_FILE not readable: $PAYLOAD_FILE" >&2; exit 1; }

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get components \
  -r "$KC_REALM" \
  -q "parentId=$LDAP_COMPONENT_ID" \
  -q providerId=group-ldap-mapper \
  -q max=500 --fields id,name --format csv --noquotes 2>/dev/null \
  > /tmp/kc_mappers_listing.txt

EXISTING_ID=$(awk -F',' -v n="$MAPPER_NAME" \
  '!/^\[/ && !/Cgroup/ && $2==n {print $1; exit}' \
  /tmp/kc_mappers_listing.txt | tr -d '\r')

if [ -n "$EXISTING_ID" ]; then
  # Inject the existing component id so kcadm performs an in-place
  # update instead of failing with "id mismatch".
  sed "s|\"name\":|\"id\": \"$EXISTING_ID\",\n    \"name\":|" \
    "$PAYLOAD_FILE" \
    | container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh update \
        "components/$EXISTING_ID" -r "$KC_REALM" -f - \
    >/dev/null 2>&1 || true
  printf '%s\n' "$EXISTING_ID"
else
  container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh create \
    components -r "$KC_REALM" -f - -i 2>/dev/null \
    < "$PAYLOAD_FILE" \
    > /tmp/kc_create_mapper.txt
  grep -vE '(^\[|Cgroup)' /tmp/kc_create_mapper.txt \
    | grep -E '^[0-9a-fA-F-]{8,}$' | head -1 | tr -d '\r'
fi
