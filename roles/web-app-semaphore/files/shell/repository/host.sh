#!/usr/bin/env bash
# Args:
#   $1  update, backup, restart, suspend, resume or release, the fixed argument of the template
#
# Env (the survey and the environment workspace apply wrote):
#   WORKSPACE_TARGETS  comma-separated <host>:<port> pairs apply pinned
#   HOST, HOST_KEY     the server and its OpenSSH host key line
#   INVENTORY_COMMIT   the commit of main update and backup run on
#   DNS_LABEL          update only, optional: the label of the host's deploy name; without it
#                      the deploy keeps the DOMAIN_PRIMARY of the inventory
#   WORKSPACE_DNS_ZONE the zone workspace apply wrote, which deploy_domain reads
#   WORKSPACE_INVENTORY_FILE  the inventory file of the checkout
#   WORKSPACE, INFINITO_SRC_DIR, SEMAPHORE_JWT, BAO_ADDR, BAO_ROLE, BAO_CACERT, EGRESS_PROXY
#                      the workspace, the core tree and the OpenBao login the
#                      host's WORKSPACE_SSH_KEY is read with
#   PLATFORM_CHECKMK_SERVER, PLATFORM_PROMETHEUS_ADDRESS  release only: both empty when the
#                      platform runs no monitoring, so release leaves the monitoring share out
set -euo pipefail

SCRIPT="host.sh"
APP_CONTROL="/usr/bin/app-control --config /etc/infinito.nexus/app-control.json"
APP_CONTROL_USER="app-control"
BACKUP_USER="backup"
MONITORING_SHARE="utils/platform_monitoring.py"
# shellcheck source=SCRIPTDIR/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Param: $@  a helper that prints a release result line on stdout only when it ends the release
# Param: TASK_WORKDIR  the task directory whose result-lines takes that line, which release_exit
#        alone prints, so no signal splits recording it from printing it
result_line() {
	"$@" >>"${TASK_WORKDIR}/result-lines"
}

# Param: $1  why the release stops, which the result line of release_exit names
# Param: $2  the exit status
stop_release() {
	release_stop="$1"
	echo "${SCRIPT}: $1" >&2
	exit "$2"
}

# Param: $1  the exit status of the task, which decides refused (2) or failed only without a recorded line
# Param: release_stop  why the release stopped, empty when a step failed without saying so
# Param: HOST, TASK_WORKDIR, release_proof  the host, the task directory and proof_of_release.py
release_exit() {
	local status="$1" code=0
	trap '' TERM HUP INT
	python3 -I "${release_proof}" finish "${HOST}" "${TASK_WORKDIR}/result-lines" "${status}" \
		"${release_stop:-host.sh stopped with exit ${status} before the release result, its stderr names why}" ||
		code=$?
	close_workdir
	exit "${code}"
}

# Param: $1  the arguments every action of release/host.py gets
# Param: $2  the stack host of HOST
# Param: $3  the digest file of the present core, the only one a never monitored host can hold
# Param: $4  the digest files of the platform record, empty for a never monitored host
release_arguments() {
	local arguments="$1"
	if [ "$2" = "${HOST}" ]; then
		arguments+=" --federation-digest ${4:-$3}"
	fi
	if [ -n "$4" ]; then
		arguments+=" --monitoring"
	fi
	echo "${arguments}"
}

# Param: $1  the inventory file
# Param: $2  the task directory of open_workdir, which holds the pinned known-hosts file
# Param: HOST, SSH_AUTH_SOCK  the host and the task agent load_workspace_key filled
release_host() {
	local inventory="$1" workdir="$2" helper proof federation shared stack current key_type key_blob
	local base arguments result status=0 flags=() named="" claimed
	helper="${INFINITO_SRC_DIR:?the runner image names no core tree}/${HELPERS_DIR}/release/host.py"
	proof="${INFINITO_SRC_DIR}/${HELPERS_DIR}/proof_of_release.py"
	federation="${INFINITO_SRC_DIR}/${HELPERS_DIR}/release/federation.py"
	shared="${INFINITO_SRC_DIR}/${MONITORING_SHARE}"
	write_agent_key "${workdir}/agent.pub"
	read -r key_type key_blob <"${workdir}/agent.pub"
	base="--login {{ ansible_user | quote }} --app-control-user ${APP_CONTROL_USER} --backup-user ${BACKUP_USER} --agent-key ${key_type} ${key_blob}"
	current="$(python3 -I "${shared}" digest-file "${INFINITO_SRC_DIR}")"
	stack="$(ansible-inventory -i "${inventory}" --list | python3 -I "${shared}" stack-host "${HOST}")"
	if [ "${stack}" != "${HOST}" ]; then
		echo "${SCRIPT}: ${HOST} is a worker of ${stack}, which holds the federation digest file of the stack" >&2
	fi
	if [ -n "${PLATFORM_CHECKMK_SERVER:-}${PLATFORM_PROMETHEUS_ADDRESS:-}" ]; then
		result_line python3 -I "${federation}" digest-files "${workdir}/digest-files" "${current}"
		read -r named <"${workdir}/digest-files"
		arguments="$(release_arguments "${base}" "${stack}" "${current}" "${named}")"
		ansible "${HOST}" -i "${inventory}" -b -t "${workdir}/check" -m ansible.builtin.script \
			-a "executable=python3 ${helper} check ${arguments}" ||
			true
		result_line python3 -I "${proof}" check "${HOST}" "${workdir}/check/${HOST}"
		result_line python3 -I "${federation}" claim "${workdir}/claimed" "${current}"
		read -r claimed <"${workdir}/claimed"
		if [ "${claimed}" != "${named}" ]; then
			stop_release "the platform record of ${HOST} changed between the check and the claim; run the release again" 1
		fi
	fi
	arguments="$(release_arguments "${base}" "${stack}" "${current}" "${named}")"
	result="${workdir}/release/${HOST}"
	if [ -z "${named}" ]; then
		ansible "${HOST}" -i "${inventory}" -b -t "${workdir}/release" -m ansible.builtin.script \
			-a "executable=python3 ${helper} apply ${arguments}" ||
			true
		result_line python3 -I "${proof}" report "${HOST}" "${result}"
	else
		ansible "${HOST}" -i "${inventory}" -b -t "${workdir}/share" -m ansible.builtin.script \
			-a "executable=python3 ${helper} share ${arguments}" ||
			true
		result_line python3 -I "${proof}" share "${HOST}" "${workdir}/share/${HOST}" "${workdir}/share.json" || status=$?
		case "${status}" in
		0)
			result_line python3 -I "${federation}" mark "${workdir}/share.json"
			ansible "${HOST}" -i "${inventory}" -b -t "${workdir}/release" -m ansible.builtin.script \
				-a "executable=python3 ${helper} apply ${arguments}" ||
				true
			flags=(--share "${workdir}/share.json")
			result_line python3 -I "${proof}" report "${flags[@]}" "${HOST}" "${result}"
			;;
		3)
			result_line python3 -I "${federation}" marked
			result="${workdir}/share/${HOST}"
			flags=(--marked)
			;;
		*) exit "${status}" ;;
		esac
		result_line python3 -I "${federation}" erase
	fi
	python3 -I "${proof}" proof-vars "${workdir}" >"${workdir}/proof-login.json"
	python3 -I "${proof}" proof-vars "${workdir}" --user root >"${workdir}/proof-root.json"
	ansible "${HOST}" -i "${inventory}" -e "@${workdir}/proof-login.json" -t "${workdir}/proof-login" \
		-m ansible.builtin.raw -a true ||
		true
	ansible "${HOST}" -i "${inventory}" -e "@${workdir}/proof-root.json" -t "${workdir}/proof-root" \
		-m ansible.builtin.raw -a true ||
		true
	result_line python3 -I "${proof}" report "${flags[@]}" "${HOST}" "${result}" \
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
domain=()
case "${action}" in
update)
	if [ -n "${DNS_LABEL:-}" ]; then
		domain=(-e "DOMAIN_PRIMARY=$(deploy_domain)")
	fi
	;;
*) refuse_set DNS_LABEL ;;
esac

if [ "${action}" = release ]; then
	release_proof="${INFINITO_SRC_DIR:-}/${HELPERS_DIR}/proof_of_release.py"
	if [ -z "${INFINITO_SRC_DIR:-}" ] || [ ! -f "${release_proof}" ]; then
		refuse "the runner image names no core tree holding ${HELPERS_DIR}/proof_of_release.py"
	fi
fi
open_workdir
workdir="${TASK_WORKDIR}"
if [ "${action}" = release ]; then
	release_stop=""
	trap 'release_exit $?' EXIT
	trap 'stop_release "host.sh got SIGTERM; run the release again" 143' TERM
	trap 'stop_release "host.sh got SIGHUP; run the release again" 129' HUP
	trap 'stop_release "host.sh got SIGINT; run the release again" 130' INT
fi
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
	infinito administration deploy dedicated "${inventory}" --skip-build --limit "${HOST}" "${domain[@]}"
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
