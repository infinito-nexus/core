#!/usr/bin/env bash
# Param: SCRIPT  the name every refusal of the sourcing script starts with

WORKSPACE_PATTERN='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
SALES_ORDER_PATTERN='^[A-Za-z][A-Za-z0-9-]{0,55}$'
LINE_PATTERN='^[1-9][0-9]{0,5}$'
DNS_LABEL_PATTERN='^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'
ROLE_PATTERN='^[a-z0-9]+(-[a-z0-9]+)*$'
COMMIT_PATTERN='^[0-9a-f]{40}$'
HOST_KEY_PATTERN='^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com) [A-Za-z0-9+/]+={0,3}$'
ZONE_PATTERN='^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$'
HELPERS_DIR="roles/web-app-semaphore/files/python"

refuse() {
	echo "${SCRIPT}: $*" >&2
	exit 2
}

# Param: $1  how many arguments the script takes
# Param: $@  after $1, the arguments the script got
refuse_arguments() {
	local expected="$1"
	shift
	if [ "$#" -gt "${expected}" ]; then
		shift "${expected}"
		refuse "unexpected argument '$1'"
	fi
	if [ "$#" -lt "${expected}" ]; then
		refuse "expects ${expected} argument(s), got $#"
	fi
}

# Param: $1  the variable name
# Param: $2  the extended regular expression its value has to match
require() {
	local name="$1" pattern="$2"
	if [ -z "${!name+set}" ] || [ -z "${!name}" ]; then
		refuse "${name} is missing"
	fi
	if [[ ! "${!name}" =~ ${pattern} ]]; then
		refuse "${name} is malformed"
	fi
}

# Param: $@  the variables the action does not take
refuse_set() {
	local name
	for name in "$@"; do
		if [ -n "${!name:-}" ]; then
			refuse "${name} is not taken by this action"
		fi
	done
}

# Param: WORKSPACE_TARGETS  comma-separated <host>:<port> pairs, IPv6 hosts in brackets
target_hosts() {
	local pair
	local -a pairs
	IFS=',' read -r -a pairs <<<"${WORKSPACE_TARGETS:-}"
	for pair in "${pairs[@]}"; do
		pair="${pair%:*}"
		pair="${pair#[}"
		printf '%s\n' "${pair%]}"
	done
}

# Param: HOST  the host the task acts on
require_target_host() {
	require HOST '^[0-9A-Fa-f:.]+$'
	if ! target_hosts | grep -Fxq -- "${HOST}"; then
		refuse "HOST ${HOST} is not the host of a pair in WORKSPACE_TARGETS"
	fi
}

# Param: TASK_WORKDIR  set to a fresh task directory, which the EXIT trap
#        removes after it killed the agent load_workspace_key starts there
open_workdir() {
	TASK_WORKDIR="$(mktemp -d)"
	TASK_AGENT_PID=""
	trap close_workdir EXIT
}

close_workdir() {
	local stopped=0
	if [ -n "${TASK_AGENT_PID}" ]; then
		kill "${TASK_AGENT_PID}" 2>/dev/null || stopped=$?
	fi
	rm -rf "${TASK_WORKDIR}"
	if [ "${stopped}" -ne 0 ] && kill -0 "${TASK_AGENT_PID}" 2>/dev/null; then
		refuse "the SSH agent ${TASK_AGENT_PID} of the task outlived it"
	fi
}

# Param: $1  the workspace inventory every later ansible call of the task reads
# Param: INFINITO_SRC_DIR  the core tree of the runner image, whose ansible.cfg
#        every later ansible call of the task reads
guard_workspace_inventory() {
	local config="${INFINITO_SRC_DIR:?the runner image names no core tree}/ansible.cfg"
	if [ ! -f "${config}" ]; then
		refuse "the core tree holds no ansible.cfg"
	fi
	export ANSIBLE_CONFIG="${config}" ANSIBLE_INVENTORY_ENABLED=yaml ANSIBLE_INVENTORY_UNPARSED_FAILED=true
	if ! ansible-inventory -i "$1" --list | python3 -I "${INFINITO_SRC_DIR}/${HELPERS_DIR}/inventory_guard.py" "${INFINITO_SRC_DIR}"; then
		refuse "the inventory is no plain YAML inventory, holds Jinja the runner would render or shadows a core setting"
	fi
}

# Param: $1  the inventory file the target host's WORKSPACE_SSH_KEY lies in
# Param: HOST, WORKSPACE  the target host and the workspace its key belongs to
# Param: INFINITO_SRC_DIR  the core tree of the runner image
# Param: TASK_WORKDIR  the task directory of open_workdir, which holds the agent socket
load_workspace_key() {
	local agent host_vars helpers
	require WORKSPACE "${WORKSPACE_PATTERN}"
	guard_workspace_inventory "$1"
	helpers="${INFINITO_SRC_DIR}/${HELPERS_DIR}"
	host_vars="$(ansible-inventory -i "$1" --host "${HOST}")"
	agent="$(ssh-agent -s -a "${TASK_WORKDIR}/agent.sock")"
	TASK_AGENT_PID="$(sed -n 's/^SSH_AGENT_PID=\([0-9][0-9]*\);.*/\1/p' <<<"${agent}")"
	if [ -z "${TASK_AGENT_PID}" ]; then
		refuse "the SSH agent of the task did not start"
	fi
	export SSH_AUTH_SOCK="${TASK_WORKDIR}/agent.sock" SSH_AGENT_PID="${TASK_AGENT_PID}"
	printf '%s' "${host_vars}" | python3 -I "${helpers}/workspace_ssh_key.py" | ssh-add -q -
	if ! printf '%s' "${host_vars}" | python3 -I "${helpers}/lockout_guard.py"; then
		refuse "the inventory would lock the login of this task out of ${HOST}"
	fi
	if ! printf '%s' "${host_vars}" | python3 -I "${helpers}/transport_guard.py"; then
		refuse "the inventory would replace the pinned SSH transport of ${HOST}"
	fi
	echo "${SCRIPT}: the SSH key of WORKSPACE_SSH_KEY is in the task agent and the inventory keeps it authorized"
}

# Param: $1  the file the one key of the task agent goes to, as one <type> <base64> line
# Param: SSH_AUTH_SOCK  the task agent load_workspace_key filled
write_agent_key() {
	local type blob
	local -a keys
	mapfile -t keys < <(ssh-add -L)
	if [ "${#keys[@]}" -ne 1 ]; then
		refuse "the task agent holds ${#keys[@]} keys where one is expected"
	fi
	read -r type blob _ <<<"${keys[0]}"
	if [[ ! "${type} ${blob}" =~ ${HOST_KEY_PATTERN} ]]; then
		refuse "the task agent holds no OpenSSH key line"
	fi
	printf '%s %s\n' "${type}" "${blob}" >"$1"
}

# Param: $1  the task directory the known-hosts file and the SSH masters live in
# Param: HOST, HOST_KEY  the host and its OpenSSH key line
pin_host_key() {
	local workdir="$1"
	require HOST_KEY "${HOST_KEY_PATTERN}"
	printf '%s %s\n' "${HOST}" "${HOST_KEY}" >"${workdir}/known_hosts"
	ssh_args "${workdir}" yes "-o UserKnownHostsFile=${workdir}/known_hosts -o GlobalKnownHostsFile=/dev/null"
}

# Param: $1  the task directory the SSH masters live in
# Param: $2  the StrictHostKeyChecking policy
# Param: $3  further ssh options
ssh_args() {
	export ANSIBLE_SSH_ARGS="-o ControlMaster=auto -o ControlPersist=60s -o ControlPath=$1/cp-%C -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=$2 -o PreferredAuthentications=publickey $3"
}

# Param: INVENTORY_COMMIT  the commit of the checkout the task acts on, which has to lie on origin/main
checkout_commit() {
	require INVENTORY_COMMIT "${COMMIT_PATTERN}"
	if ! git merge-base --is-ancestor "${INVENTORY_COMMIT}" refs/remotes/origin/main 2>/dev/null; then
		refuse "INVENTORY_COMMIT ${INVENTORY_COMMIT} is not on main"
	fi
	git checkout --quiet --detach "${INVENTORY_COMMIT}"
	if [ "$(git rev-parse HEAD)" != "${INVENTORY_COMMIT}" ]; then
		refuse "INVENTORY_COMMIT ${INVENTORY_COMMIT} is not the checked-out HEAD"
	fi
	echo "${SCRIPT}: inventory at ${INVENTORY_COMMIT}"
}

# Param: $1  the inventory file, relative to the checkout
workspace_inventory() {
	local inventory="${PWD}/$1"
	if [ ! -f "${inventory}" ]; then
		refuse "the inventory repository holds no $1"
	fi
	printf '%s\n' "${inventory}"
}
