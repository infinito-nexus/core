#!/bin/bash
# Delete the shared default 'ldap-roles' group-ldap-mapper that
# update/05_ldap.yml maintains for the assert/05_ldap.yml contract.
# The per-application mappers (ldap-roles-<app>) replace it; leaving
# the default mapper in place would re-import every LDAP groupOfNames
# flat under /roles on every sync and shadow the per-app structure.
#
# Required env:
#   KC_CONTAINER         keycloak container name
#   KC_REALM             realm name
#   LDAP_COMPONENT_ID    Keycloak LDAP component id
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${LDAP_COMPONENT_ID:?LDAP_COMPONENT_ID is required}"

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh get components \
  -r "$KC_REALM" \
  -q "parentId=$LDAP_COMPONENT_ID" \
  -q providerId=group-ldap-mapper \
  --fields id,name --format csv --noquotes 2>/dev/null \
  | tr -d '\r' \
  | awk -F',' '$2=="ldap-roles"{print $1}' \
  > /tmp/kc_ldap_roles_ids.txt

while IFS= read -r m_id; do
  [ -z "$m_id" ] && continue
  container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh delete \
    "components/$m_id" -r "$KC_REALM" </dev/null || true
done < /tmp/kc_ldap_roles_ids.txt
