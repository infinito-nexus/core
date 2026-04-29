#!/bin/bash
# Trigger a one-shot federation -> Keycloak sync on the per-app mapper.
#
# Required env:
#   KC_CONTAINER         keycloak container name
#   KC_REALM             realm name
#   LDAP_COMPONENT_ID    Keycloak LDAP component id
#   MAPPER_ID            Keycloak mapper id to sync
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${LDAP_COMPONENT_ID:?LDAP_COMPONENT_ID is required}"
: "${MAPPER_ID:?MAPPER_ID is required}"

container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh create \
  "user-storage/$LDAP_COMPONENT_ID/mappers/$MAPPER_ID/sync?direction=fedToKeycloak" \
  -r "$KC_REALM" 2>&1 || true
