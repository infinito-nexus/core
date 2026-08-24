#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Ensure a Keycloak realm user exists with the desired profile/password.
#
# Runs on the host and executes kcadm inside the Keycloak container.
#
# REQUIRED environment variables:
#   KEYCLOAK_EXEC_CONTAINER
#   KEYCLOAK_KCADM
#   KEYCLOAK_REALM
#   KEYCLOAK_USERNAME
#   KEYCLOAK_PASSWORD
#
# OPTIONAL:
#   KEYCLOAK_EMAIL
#   KEYCLOAK_FIRSTNAME
#   KEYCLOAK_LASTNAME
#   KEYCLOAK_USER_ENABLED   true|false (default: true)
###############################################################################

: "${KEYCLOAK_EXEC_CONTAINER:?missing KEYCLOAK_EXEC_CONTAINER}"
: "${KEYCLOAK_KCADM:?missing KEYCLOAK_KCADM}"
: "${KEYCLOAK_REALM:?missing KEYCLOAK_REALM}"
: "${KEYCLOAK_USERNAME:?missing KEYCLOAK_USERNAME}"
: "${KEYCLOAK_PASSWORD:?missing KEYCLOAK_PASSWORD}"

KEYCLOAK_EMAIL="${KEYCLOAK_EMAIL:-}"
KEYCLOAK_FIRSTNAME="${KEYCLOAK_FIRSTNAME:-}"
KEYCLOAK_LASTNAME="${KEYCLOAK_LASTNAME:-}"
KEYCLOAK_USER_ENABLED="${KEYCLOAK_USER_ENABLED:-true}"

# shellcheck disable=SC2016 # Inner $vars are intentionally expanded by the container shell, not the host.
${KEYCLOAK_EXEC_CONTAINER} sh -lc '
  set -euo pipefail

  USERNAME="$1"
  PASSWORD="$2"
  REALM="$3"
  EMAIL="$4"
  FIRSTNAME="$5"
  LASTNAME="$6"
  ENABLED="$7"
  KCADM="$8"

  RAW="$($KCADM get users -r "$REALM" -q username="$USERNAME" --fields id --format csv --noquotes 2>&1 || true)"
  USER_ID="$(printf "%s\n" "$RAW" \
    | grep -Eio "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" \
    | head -n1 || true)"

  CREATED=false
  if [ -z "${USER_ID:-}" ]; then
    $KCADM create users -r "$REALM" \
      -s "username=$USERNAME" \
      -s "enabled=$ENABLED" \
      -s "email=$EMAIL" \
      -s "firstName=$FIRSTNAME" \
      -s "lastName=$LASTNAME"
    CREATED=true

    RAW="$($KCADM get users -r "$REALM" -q username="$USERNAME" --fields id --format csv --noquotes 2>&1 || true)"
    USER_ID="$(printf "%s\n" "$RAW" \
      | grep -Eio "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" \
      | head -n1 || true)"
  fi

  if [ -z "${USER_ID:-}" ]; then
    echo "[keycloak][user] failed to resolve user id for $USERNAME in realm $REALM" >&2
    exit 1
  fi

  $KCADM update users/$USER_ID -r "$REALM" \
    -s "enabled=$ENABLED" \
    -s "email=$EMAIL" \
    -s "firstName=$FIRSTNAME" \
    -s "lastName=$LASTNAME"

  $KCADM set-password -r "$REALM" \
    --username "$USERNAME" \
    --new-password "$PASSWORD"

  if [ "$CREATED" = true ]; then
    echo "[keycloak][user] created: $USERNAME ($USER_ID)"
  else
    echo "[keycloak][user] updated: $USERNAME ($USER_ID)"
  fi
' sh \
  "${KEYCLOAK_USERNAME}" \
  "${KEYCLOAK_PASSWORD}" \
  "${KEYCLOAK_REALM}" \
  "${KEYCLOAK_EMAIL}" \
  "${KEYCLOAK_FIRSTNAME}" \
  "${KEYCLOAK_LASTNAME}" \
  "${KEYCLOAK_USER_ENABLED}" \
  "${KEYCLOAK_KCADM}"
