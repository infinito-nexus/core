#!/usr/bin/env bash
# Env of the survey:
#   WORKSPACE         the workspace id, a lowercase UUID
#   MEMBERS_ACTION    sync, list, add, invite, uninvite, role or remove
#   WORKSPACE_MEMBER  a Keycloak user id, for add, role and remove
#   INVITE_KEY        the store's lowercase UUID key of a staged invitation, for invite and uninvite
#   WORKSPACE_ROLE    Owner, Admin, Operator, Billing or Viewer, for role
#   WORKSPACE_SUSPENDED  true while the store suspends the workspace for non-payment, else false, for every action
#
# Env of the Workspaces project:
#   KC_URL, KC_REALM, KC_CLIENT_ID, KC_INVITE_CLIENT_ID, KC_RBAC_GROUP_ROOT  the Keycloak side
#   KC_SIGN_IN_GROUP   the RBAC group a member signs in to Semaphore with, which remove takes them out of
#   KC_CLIENT_SECRET   the secret of the client workspace-members, a Semaphore secret
#   BAO_ADDR, BAO_ROLE, BAO_CACERT  the OpenBao task-token login of invite (role members)
#   SEMAPHORE_JWT      the task token Semaphore hands every task
#   SEMAPHORE_API_URL, SEMAPHORE_ADMIN_USERNAME, SEMAPHORE_API_TOKEN_NAME,
#   SEMAPHORE_STORE_USERNAME, SEMAPHORE_DB_HOST, SEMAPHORE_DB_PORT, SEMAPHORE_DB,
#   SEMAPHORE_DB_USER, SEMAPHORE_DB_PASS  the Semaphore side
#   INFINITO_SRC_DIR   the core tree of the runner image
set -euo pipefail

SCRIPT="members.sh"
here="$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=SCRIPTDIR/lib.sh
source "${here}/lib.sh"

KEYCLOAK_ID_PATTERN='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
ROLE_NAME_PATTERN='^(Owner|Admin|Operator|Billing|Viewer)$'

refuse_arguments 0 "$@"
require WORKSPACE "${WORKSPACE_PATTERN}"
require MEMBERS_ACTION '^(sync|list|add|invite|uninvite|role|remove)$'
require WORKSPACE_SUSPENDED '^(true|false)$'
case "${MEMBERS_ACTION}" in
sync | list)
	refuse_set WORKSPACE_MEMBER INVITE_KEY WORKSPACE_ROLE
	;;
add | remove)
	refuse_set INVITE_KEY WORKSPACE_ROLE
	require WORKSPACE_MEMBER "${KEYCLOAK_ID_PATTERN}"
	;;
invite | uninvite)
	refuse_set WORKSPACE_MEMBER WORKSPACE_ROLE
	require INVITE_KEY "${WORKSPACE_PATTERN}"
	;;
role)
	refuse_set INVITE_KEY
	require WORKSPACE_MEMBER "${KEYCLOAK_ID_PATTERN}"
	require WORKSPACE_ROLE "${ROLE_NAME_PATTERN}"
	;;
esac

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
export KC_CLIENT_SECRET_FILE="${workdir}/client-secret"
(umask 077 && printf '%s' "${KC_CLIENT_SECRET:?the project environment carries no client secret}" >"${KC_CLIENT_SECRET_FILE}")
unset KC_CLIENT_SECRET
export MEMBERS_ROSTER_FILE="${workdir}/roster.json"
if [ "${MEMBERS_ACTION}" = invite ]; then
	export BAO_TOKEN_FILE="${workdir}/bao-token"
	python3 "${here}/../../python/bao/login.py" "${BAO_TOKEN_FILE}"
fi
keycloak="${INFINITO_SRC_DIR:?the runner image names no core tree}/roles/web-app-keycloak/files/python"
export PYTHONPATH="${keycloak}:${keycloak}/workspace"

if [ "${MEMBERS_ACTION}" = list ]; then
	python3 "${keycloak}/workspace/members.py" list
	exit 0
fi
python3 "${keycloak}/workspace/members.py" prepare
if [ "${MEMBERS_ACTION}" = remove ]; then
	python3 "${here}/../../python/semaphore_members.py" remove
fi
status=0
python3 "${keycloak}/workspace/members.py" settle >"${workdir}/settle.out" || status=$?
if [ "${status}" -ne 0 ]; then
	cat "${workdir}/settle.out"
	exit "${status}"
fi
head -n -1 "${workdir}/settle.out"
python3 "${here}/../../python/semaphore_members.py" sync "${MEMBERS_ROSTER_FILE}"
tail -n 1 "${workdir}/settle.out"
