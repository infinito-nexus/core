#!/usr/bin/env bash
# Env of the survey:
#   USER_ACTION  erase
#   USER_ID      a Keycloak user id
#
# Env of the Workspaces project:
#   KC_URL, KC_REALM, KC_CLIENT_ID, KC_RBAC_GROUP_ROOT  the Keycloak side
#   KC_CLIENT_SECRET  the secret of the client workspace-members, a Semaphore secret
#   INFINITO_SRC_DIR  the core tree of the runner image
set -euo pipefail

SCRIPT="user.sh"
# shellcheck source=SCRIPTDIR/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

refuse_arguments 0 "$@"
require USER_ACTION '^erase$'
require USER_ID '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
export KC_CLIENT_SECRET_FILE="${workdir}/client-secret"
(umask 077 && printf '%s' "${KC_CLIENT_SECRET:?the project environment carries no client secret}" >"${KC_CLIENT_SECRET_FILE}")
unset KC_CLIENT_SECRET
keycloak="${INFINITO_SRC_DIR:?the runner image names no core tree}/roles/web-app-keycloak/files/python"
export PYTHONPATH="${keycloak}:${keycloak}/workspace"
python3 "${keycloak}/workspace/user.py"
