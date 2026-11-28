#!/usr/bin/env bash
# Env of the survey:
#   WORKSPACE         the bare lowercase id of the workspace the store dispatches the run for
#   MONITOR_ACTION    apply or remove
#   MONITOR_HOST      the one inventory host the run converges; no other host is touched
#   INVENTORY_COMMIT  apply only: the pinned commit of the workspace repository the host is read from
#   DNS_LABEL         apply only: the label of the host's deploy name, which deploy_domain of lib.sh
#                     joins with the DNS zone workspace apply handed to OpenBao into its DOMAIN_PRIMARY
#
# Env of the Workspaces project (the deploy project's inventory, key and environment):
#   DEPLOY_VAULT_PASSWORD       vault password of the platform inventory, a Semaphore secret
#   DEPLOY_LOGIN                account the run signs in to the platform's Prometheus host as
#   DEPLOY_KNOWN_HOSTS          known_hosts lines pinning the platform host keys
#   WORKSPACE_INVENTORY_FILE    the inventory file of the platform inventory checkout
#   SSH_AUTH_SOCK               agent holding the deploy key
#   BAO_ADDR, BAO_CACERT        the OpenBao the monitoring credentials lie in
#   BAO_MONITORING_ROLE         the task token role of the monitoring template
#   SEMAPHORE_JWT               the task token Semaphore hands every task
#   MONITOR_INVENTORY_REPOSITORY  the workspace inventory repository, {workspace} for ws-<id>; the run
#                               reads MONITOR_HOST from INVENTORY_COMMIT, which has to lie on its main
#   MONITOR_INVENTORY_FILE      the inventory file of a workspace inventory checkout
#   MONITOR_CHECKMK_API, MONITOR_CHECKMK_SITE, MONITOR_CACERT  the platform's Checkmk
#   MONITOR_TLS_WARN_DAYS, MONITOR_TLS_CRIT_DAYS  the TLS expiry levels of web-app-checkmk
#   MONITOR_PROMETHEUS_DIR      the directory the platform's Prometheus reads instance scrape files from
#   MONITOR_PROMETHEUS_RELOAD_URL  its lifecycle reload endpoint, as its host reaches it
#   INFINITO_SRC_DIR            the core tree of the runner image
set -euo pipefail

SCRIPT="monitoring.sh"
PROMETHEUS_HOSTS="web-app-prometheus[0]"
UNDO_FAILED=4
here="$(dirname "${BASH_SOURCE[0]}")"
helpers="$(realpath "${here}/../../python")"
# shellcheck source=SCRIPTDIR/lib.sh
source "${here}/lib.sh"

exec 3>&1
refuse() {
	echo "${SCRIPT}: $*" >&2
	python3 -I "${helpers}/monitoring.py" refuse "$*" >&3
	exit 2
}

# Param: $1  the state file monitoring.py prometheus wrote
# Param: $2  the directory the Prometheus host's result lands in
push_prometheus() {
	local staged="/run/${alias}.monitoring.json"
	ansible "${PROMETHEUS_HOSTS}" -i "${platform}" --vault-password-file "${password_file}" -u "${DEPLOY_LOGIN}" -b \
		-m ansible.builtin.copy -a "src=$1 dest=${staged} mode=0600" >/dev/null || return 1
	ansible "${PROMETHEUS_HOSTS}" -i "${platform}" --vault-password-file "${password_file}" -u "${DEPLOY_LOGIN}" -b \
		-t "$2" -m ansible.builtin.script \
		-a "executable=python3 ${helpers}/prometheus_instances.py apply --dir ${MONITOR_PROMETHEUS_DIR} --state ${staged} --reload-url ${MONITOR_PROMETHEUS_RELOAD_URL}" >/dev/null
}

# Param: MONITOR_HOST, workdir  the host whose apply this run takes back
# Param: undo_left  set to what the undo could not take back, empty once it took back everything
undo_apply() {
	undo_left=""
	export MONITOR_ACTION=remove INVENTORY_COMMIT="" DNS_LABEL="" MONITOR_UNDO=1
	if ! printf '{}' >"${workdir}/undo-inventory.json" ||
		! python3 "${helpers}/monitoring.py" plan "${workdir}/undo-inventory.json" "${workdir}/undo.json" ""; then
		undo_left=" token, digest and agent key; scrape file; Checkmk host;"
		return 1
	fi
	python3 "${helpers}/monitoring.py" secrets "${workdir}/undo.json" "${workdir}/undo-secrets.json" ||
		undo_left+=" token, digest and agent key;"
	if ! python3 "${helpers}/monitoring.py" prometheus "${workdir}/undo.json" "${workdir}/undo-secrets.json" "${workdir}/undo-state.json" ||
		! push_prometheus "${workdir}/undo-state.json" "${workdir}/undo-prometheus"; then
		undo_left+=" scrape file;"
	fi
	python3 "${helpers}/monitoring.py" checkmk "${workdir}/undo.json" "${workdir}/checkmk-login.json" "${workdir}/undo-checkmk.json" ||
		undo_left+=" Checkmk host;"
	[ -z "${undo_left}" ]
}

# Param: $1  the exit status of the signal, which the run keeps once the undo took back everything
# Param: applied  1 while an apply holds writes no settle confirmed
interrupted() {
	if [ "${applied}" = 1 ]; then
		echo "${SCRIPT}: interrupted while applying ${MONITOR_HOST}; taking the apply back" >&2
	fi
	finish "$1"
}

# Param: $1  the exit status the run ends with
# Param: applied  1 while an apply holds writes no settle confirmed, which the exit takes back
finish() {
	local status="$1" refused=0
	if [ "${applied}" = 1 ]; then
		trap '' TERM HUP INT
		applied=0
		if ! undo_apply; then
			echo "${SCRIPT}: undoing the apply of ${MONITOR_HOST} in ${alias} left its${undo_left%;} behind; run monitoring remove for ${MONITOR_HOST}" >&2
			python3 -I "${helpers}/monitoring.py" refuse "undoing the apply of ${MONITOR_HOST} left its${undo_left%;} behind: run monitoring remove for ${MONITOR_HOST}" >&3 || refused=$?
			if [ "${refused}" -ne 0 ] && [ "${refused}" -ne 2 ]; then
				echo "${SCRIPT}: printing the refusal line of ${MONITOR_HOST} failed with exit ${refused}" >&2
			fi
			status="${UNDO_FAILED}"
		fi
	fi
	rm -rf "${workdir}"
	exit "${status}"
}

refuse_arguments 0 "$@"
refuse_set MONITOR_UNDO
workdir="$(mktemp -d)"
applied=0
trap 'finish $?' EXIT
trap 'interrupted 143' TERM
trap 'interrupted 129' HUP
trap 'interrupted 130' INT
export BAO_TOKEN_FILE="${workdir}/bao-token"
python3 -I "${helpers}/monitoring.py" validate
alias="ws-${WORKSPACE}"

platform="$(workspace_inventory "${WORKSPACE_INVENTORY_FILE}")"
password_file="${workdir}/vault-password"
(umask 077 && printf '%s' "${DEPLOY_VAULT_PASSWORD}" >"${password_file}")
chmod 0400 "${password_file}"
unset DEPLOY_VAULT_PASSWORD
known=""
if [ -n "${DEPLOY_KNOWN_HOSTS}" ]; then
	printf '%s\n' "${DEPLOY_KNOWN_HOSTS}" >"${workdir}/known_hosts"
	known="-o UserKnownHostsFile=${workdir}/known_hosts"
fi
ssh_args "${workdir}" accept-new "${known}"

BAO_ROLE="${BAO_MONITORING_ROLE}" python3 "${helpers}/bao/login.py" "${BAO_TOKEN_FILE}"
domain=""
if [ "${MONITOR_ACTION}" = apply ]; then
	python3 "${helpers}/monitoring.py" inventory-key "${workdir}/inventory-key" "${workdir}/dns-zone"
	read -r WORKSPACE_DNS_ZONE <"${workdir}/dns-zone"
	domain="$(deploy_domain)"
fi

listed="$(ansible "${PROMETHEUS_HOSTS}" -i "${platform}" --vault-password-file "${password_file}" --list-hosts)"
counted=0
prometheus_hosts="$(printf '%s\n' "${listed}" | tail -n +2 | grep -c .)" || counted=$?
if [ "${counted}" -gt 1 ]; then
	exit "${counted}"
fi
if [ "${prometheus_hosts}" -ne 1 ]; then
	refuse "the platform inventory names ${prometheus_hosts} Prometheus hosts where one is expected"
fi

if [ "${MONITOR_ACTION}" = apply ]; then
	repository="${MONITOR_INVENTORY_REPOSITORY}"
	GIT_SSH_COMMAND="ssh -i ${workdir}/inventory-key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${workdir}/git_known_hosts" \
		git clone --quiet --branch main "${repository//\{workspace\}/${alias}}" "${workdir}/inventory"
	(cd "${workdir}/inventory" && checkout_commit)
	linked="$(find "${workdir}/inventory" -path "${workdir}/inventory/.git" -prune -o -type l -print -quit)"
	if [ -n "${linked}" ]; then
		refuse "the inventory repository of ${alias} holds the symlink ${linked#"${workdir}/inventory/"}"
	fi
	workspace_file="${workdir}/inventory/${MONITOR_INVENTORY_FILE}"
	if [ ! -f "${workspace_file}" ]; then
		refuse "the inventory repository of ${alias} holds no ${MONITOR_INVENTORY_FILE}"
	fi
	guard_workspace_inventory "${workspace_file}"
	ansible-inventory -i "${workspace_file}" --list >"${workdir}/inventory.json"
else
	printf '{}' >"${workdir}/inventory.json"
fi

python3 "${helpers}/monitoring.py" plan "${workdir}/inventory.json" "${workdir}/plan.json" "${domain}"
python3 "${helpers}/monitoring.py" preflight "${workdir}/plan.json" "${workdir}/checkmk-login.json"
install -d -m 0700 "${HOME}/.ssh"
if [ "${MONITOR_ACTION}" = apply ]; then
	applied=1
	python3 "${helpers}/monitoring.py" secrets "${workdir}/plan.json" "${workdir}/secrets.json"
	python3 "${helpers}/monitoring.py" checkmk "${workdir}/plan.json" "${workdir}/checkmk-login.json" "${workdir}/checkmk.json"
else
	python3 "${helpers}/monitoring.py" checkmk "${workdir}/plan.json" "${workdir}/checkmk-login.json" "${workdir}/checkmk.json"
	python3 "${helpers}/monitoring.py" secrets "${workdir}/plan.json" "${workdir}/secrets.json"
fi
python3 "${helpers}/monitoring.py" prometheus "${workdir}/plan.json" "${workdir}/secrets.json" "${workdir}/prometheus-state.json"

push_prometheus "${workdir}/prometheus-state.json" "${workdir}/prometheus"
mapfile -t trees < <(find "${workdir}/prometheus" -type f)
if [ "${#trees[@]}" -ne 1 ]; then
	echo "${SCRIPT}: the Prometheus host answered ${#trees[@]} results where one is expected" >&2
	exit 1
fi

if [ "${MONITOR_ACTION}" = apply ]; then
	settled=0
	python3 "${helpers}/monitoring.py" settle "${workdir}/plan.json" || settled=$?
	if [ "${settled}" -eq 3 ]; then
		refuse "host ${MONITOR_HOST} was released in ${alias} while this apply ran: its Checkmk host, scrape file and records are removed again"
	fi
	if [ "${settled}" -ne 0 ]; then
		exit "${settled}"
	fi
	applied=0
fi

python3 "${helpers}/monitoring.py" result "${workdir}/plan.json" "${workdir}/checkmk.json" "${trees[0]}"
