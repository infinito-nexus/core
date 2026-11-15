#!/usr/bin/env bash
# Args:
#   $1  update, backup, restart, suspend, resume or release, the fixed argument of the template
#
# Env (the survey and the environment workspace apply wrote):
#   WORKSPACE_TARGETS  comma-separated <host>:<port> pairs apply pinned
#   HOST, HOST_KEY     the server and its OpenSSH host key line
#   INVENTORY_COMMIT   the commit of main update and backup run on
#   WORKSPACE_INVENTORY_FILE  the inventory file of the checkout
#   WORKSPACE, INFINITO_SRC_DIR, SEMAPHORE_JWT, BAO_ADDR, BAO_ROLE, BAO_CACERT, EGRESS_PROXY
#                      the workspace, the core tree and the OpenBao login the
#                      host's WORKSPACE_SSH_KEY is read with
set -euo pipefail

SCRIPT="host.sh"
APP_CONTROL="/usr/bin/app-control --config /etc/infinito.nexus/app-control.json"
APP_CONTROL_USER="app-control"
BACKUP_USER="backup"
# shellcheck source=SCRIPTDIR/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Param: $1  the inventory file
# Param: $2  the task directory of open_workdir, which holds the pinned known-hosts file
# Param: HOST, SSH_AUTH_SOCK  the host and the task agent load_workspace_key filled
release_host() {
	local inventory="$1" workdir="$2" helper proof key_type key_blob
	helper="${INFINITO_SRC_DIR:?the runner image names no core tree}/${HELPERS_DIR}/release_host.py"
	proof="${INFINITO_SRC_DIR}/${HELPERS_DIR}/proof_of_release.py"
	write_agent_key "${workdir}/agent.pub"
	read -r key_type key_blob <"${workdir}/agent.pub"
	ansible "${HOST}" -i "${inventory}" -b -t "${workdir}/release" -m ansible.builtin.script \
		-a "executable=python3 ${helper} apply --login {{ ansible_user | quote }} --app-control-user ${APP_CONTROL_USER} --backup-user ${BACKUP_USER} --agent-key ${key_type} ${key_blob}" ||
		true
	python3 -I "${proof}" report "${HOST}" "${workdir}/release/${HOST}"
	python3 -I "${proof}" proof-vars "${workdir}" >"${workdir}/proof-login.json"
	python3 -I "${proof}" proof-vars "${workdir}" --user root >"${workdir}/proof-root.json"
	ansible "${HOST}" -i "${inventory}" -e "@${workdir}/proof-login.json" -t "${workdir}/proof-login" \
		-m ansible.builtin.raw -a true ||
		true
	ansible "${HOST}" -i "${inventory}" -e "@${workdir}/proof-root.json" -t "${workdir}/proof-root" \
		-m ansible.builtin.raw -a true ||
		true
	python3 -I "${proof}" report "${HOST}" "${workdir}/release/${HOST}" \
		"${workdir}/proof-login/${HOST}" "${workdir}/proof-root/${HOST}"
}

refuse_arguments 1 "$@"
action="$1"
case "${action}" in
update | backup) commit=required ;;
restart | suspend | resume | release)
	refuse_set INVENTORY_COMMIT
	commit=refused
	;;
*) refuse "unknown action '${action}'" ;;
esac
require_target_host
require HOST_KEY "${HOST_KEY_PATTERN}"
if [ "${commit}" = required ]; then
	require INVENTORY_COMMIT "${COMMIT_PATTERN}"
fi

open_workdir
workdir="${TASK_WORKDIR}"
pin_host_key "${workdir}"
if [ "${commit}" = required ]; then
	checkout_commit
fi
inventory="$(workspace_inventory "${WORKSPACE_INVENTORY_FILE:?the environment names no inventory file}")"
load_workspace_key "${inventory}"
install -d -m 0700 "${HOME}/.ssh"
echo "${SCRIPT}: ${action} on ${HOST}"

case "${action}" in
update)
	infinito administration deploy dedicated "${inventory}" --skip-build --limit "${HOST}"
	;;
backup)
	ansible "${HOST}" -i "${inventory}" -b -m ansible.builtin.command \
		-a "systemctl start svc-bkp-volume-2-local.*.service"
	;;
restart)
	ansible "${HOST}" -i "${inventory}" -b -m ansible.builtin.reboot
	;;
suspend)
	ansible "${HOST}" -i "${inventory}" -b -m ansible.builtin.command -a "${APP_CONTROL} stop all"
	;;
resume)
	ansible "${HOST}" -i "${inventory}" -b -m ansible.builtin.command -a "${APP_CONTROL} start all"
	;;
release)
	release_host "${inventory}" "${workdir}"
	;;
esac
