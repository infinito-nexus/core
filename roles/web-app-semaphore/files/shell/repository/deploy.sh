#!/usr/bin/env bash
# Args:
#   $1  the inventory file, relative to the inventory repository Semaphore
#       checked out as the working directory
#
# Env of the platform deploy (the project environment and the inventory):
#   DEPLOY_VAULT_PASSWORD  vault password of the inventory, a Semaphore secret;
#                          required only while the inventory holds a !vault block
#   DEPLOY_LOGIN           account the deploy signs in to every host as
#   DEPLOY_KNOWN_HOSTS     known_hosts lines pinning host keys; empty keeps the
#                          accept-new policy of ansible.cfg
#   SSH_AUTH_SOCK          agent holding the deploy key of the inventory
#
# Env of a workspace deploy (WORKSPACE set; the survey and the environment
# workspace apply wrote):
#   WORKSPACE           the workspace id, a lowercase UUID
#   WORKSPACE_DNS_ZONE  the zone the deploy name lies in
#   WORKSPACE_TARGETS   comma-separated <host>:<port> pairs apply pinned
#   SALES_ORDER, LINE   the order line this deploy serves
#   HOST, HOST_KEY      the server and its OpenSSH host key line
#   ROLES               comma-separated role names of the runner image's core tree
#   DNS_LABEL           the label of the deploy name
#   INVENTORY_COMMIT    the commit of main the deploy runs on
#   INFINITO_SRC_DIR    the core tree of the runner image
#   SEMAPHORE_JWT, BAO_ADDR, BAO_ROLE, BAO_CACERT, EGRESS_PROXY
#                       the OpenBao login the host's WORKSPACE_SSH_KEY is read with
set -euo pipefail

SCRIPT="deploy.sh"
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

refuse_arguments 1 "$@"

open_workdir
workdir="${TASK_WORKDIR}"

if [ -n "${WORKSPACE:-}" ]; then
	require WORKSPACE "${WORKSPACE_PATTERN}"
	require WORKSPACE_DNS_ZONE "${ZONE_PATTERN}"
	require SALES_ORDER "${SALES_ORDER_PATTERN}"
	require LINE "${LINE_PATTERN}"
	require_target_host
	require HOST_KEY "${HOST_KEY_PATTERN}"
	require ROLES "^[a-z0-9-]+(,[a-z0-9-]+)*$"
	require DNS_LABEL "${DNS_LABEL_PATTERN}"
	require INVENTORY_COMMIT "${COMMIT_PATTERN}"
	IFS=',' read -r -a roles <<<"${ROLES}"
	for role in "${roles[@]}"; do
		if [[ ! "${role}" =~ ${ROLE_PATTERN} ]] || [ ! -d "${INFINITO_SRC_DIR:?the runner image names no core tree}/roles/${role}" ]; then
			refuse "ROLES names ${role}, which the runner image's core tree does not hold"
		fi
	done
	checkout_commit
	inventory="$(workspace_inventory "$1")"
	domain="${DNS_LABEL}.ws-${WORKSPACE}.${WORKSPACE_DNS_ZONE}"
	pin_host_key "${workdir}"
	load_workspace_key "${inventory}"
	echo "${SCRIPT}: deploying ${ROLES} of ${SALES_ORDER}/${LINE} to ${HOST} as ${domain}"
	exec_args=(--id "${roles[@]}" --limit "${HOST}" -e "DOMAIN_PRIMARY=${domain}")
else
	: "${DEPLOY_LOGIN:?the project environment names no login}"
	: "${DEPLOY_KNOWN_HOSTS?the project environment declares no known_hosts}"
	: "${SSH_AUTH_SOCK:?the inventory carries no SSH key}"
	inventory="$(workspace_inventory "$1")"
	vault_args=()
	inventory_dir="$(dirname "${inventory}")"
	if grep -rqsF -- '!vault' "${inventory}" "${inventory_dir}/group_vars" "${inventory_dir}/host_vars"; then
		: "${DEPLOY_VAULT_PASSWORD:?the inventory holds a vault block but the project environment carries no vault password}"
		password_file="${workdir}/vault-password"
		(umask 077 && printf '%s' "${DEPLOY_VAULT_PASSWORD}" >"${password_file}")
		chmod 0400 "${password_file}"
		vault_args=(--password-file "${password_file}")
	fi
	unset DEPLOY_VAULT_PASSWORD
	known=""
	if [ -n "${DEPLOY_KNOWN_HOSTS}" ]; then
		printf '%s\n' "${DEPLOY_KNOWN_HOSTS}" >"${workdir}/known_hosts"
		known="-o UserKnownHostsFile=${workdir}/known_hosts"
	fi
	ssh_args "${workdir}" accept-new "${known}"
	exec_args=("${vault_args[@]}" -u "${DEPLOY_LOGIN}")
fi
install -d -m 0700 "${HOME}/.ssh"

infinito administration deploy dedicated "${inventory}" --skip-build "${exec_args[@]}"
