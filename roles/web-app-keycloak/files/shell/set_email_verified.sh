#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Set emailVerified for a Keycloak user (robust against noisy kcadm output)
#
# Runs on the host and executes kcadm inside the Keycloak container.
#
# REQUIRED environment variables:
#   KEYCLOAK_EXEC_CONTAINER   e.g. "container exec -i keycloak"
#   KEYCLOAK_KCADM            e.g. "/opt/keycloak/bin/kcadm.sh"
#   KEYCLOAK_REALM            Realm name
#   KEYCLOAK_USERNAME         Username to update
#
# OPTIONAL:
#   KEYCLOAK_EMAIL_VERIFIED   true|false (default: true)
###############################################################################

: "${KEYCLOAK_EXEC_CONTAINER:?missing KEYCLOAK_EXEC_CONTAINER}"
: "${KEYCLOAK_KCADM:?missing KEYCLOAK_KCADM}"
: "${KEYCLOAK_REALM:?missing KEYCLOAK_REALM}"
: "${KEYCLOAK_USERNAME:?missing KEYCLOAK_USERNAME}"

KEYCLOAK_EMAIL_VERIFIED="${KEYCLOAK_EMAIL_VERIFIED:-true}"

${KEYCLOAK_EXEC_CONTAINER} sh -lc "
  set -euo pipefail

  USERNAME=\"${KEYCLOAK_USERNAME}\"
  REALM=\"${KEYCLOAK_REALM}\"
  VERIFIED=\"${KEYCLOAK_EMAIL_VERIFIED}\"

  RAW=\"\$(${KEYCLOAK_KCADM} get users -r \"\$REALM\" -q username=\"\$USERNAME\" --fields id --format csv --noquotes 2>&1 || true)\"

  USER_ID=\"\$(printf '%s\n' \"\$RAW\" \
    | grep -Eio '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' \
    | head -n1 || true)\"

  if [ -z \"\${USER_ID:-}\" ]; then
    echo \"[keycloak][emailVerified] user not found: \$USERNAME\" >&2
    exit 0
  fi

  CURRENT_RAW=\"\$(${KEYCLOAK_KCADM} get users/\$USER_ID -r \"\$REALM\" 2>&1 || true)\"

  CURRENT_LINE=\"\$(printf '%s\n' \"\$CURRENT_RAW\" \
    | tr -d '\r' \
    | grep -Eo '\"emailVerified\"[[:space:]]*:[[:space:]]*(true|false)' \
    | head -n1 || true)\"

  CURRENT=\"\$(printf '%s' \"\$CURRENT_LINE\" \
    | sed -E 's/.*:[[:space:]]*(true|false).*/\\1/' \
    | tr -d ' ' \
    || true)\"

  if [ \"\${CURRENT:-}\" = \"\$VERIFIED\" ]; then
    echo \"[keycloak][emailVerified] unchanged: \$USERNAME (\$USER_ID) = \$CURRENT\"
    exit 0
  fi

  ${KEYCLOAK_KCADM} update users/\$USER_ID -r \"\$REALM\" -s emailVerified=\"\$VERIFIED\"

  echo \"[keycloak][emailVerified] updated: \$USERNAME (\$USER_ID) -> \$VERIFIED\"
"
