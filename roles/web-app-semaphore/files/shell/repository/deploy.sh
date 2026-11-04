#!/usr/bin/env bash
# Args:
#   $1  the inventory file, relative to the inventory repository Semaphore
#       checked out as the working directory
#
# Env (the project environment and the inventory Semaphore runs the template with):
#   DEPLOY_VAULT_PASSWORD  vault password of the inventory, a Semaphore secret
#   DEPLOY_LOGIN           account the deploy signs in to every host as
#   DEPLOY_KNOWN_HOSTS     known_hosts lines pinning host keys; empty keeps the
#                          accept-new policy of ansible.cfg
#   SSH_AUTH_SOCK          agent holding the deploy key of the inventory
set -euo pipefail

if [ "$#" -ne 1 ]; then
	echo "usage: deploy.sh <inventory file>" >&2
	exit 2
fi
: "${DEPLOY_VAULT_PASSWORD:?the project environment carries no vault password}"
: "${DEPLOY_LOGIN:?the project environment names no login}"
: "${DEPLOY_KNOWN_HOSTS?the project environment declares no known_hosts}"
: "${SSH_AUTH_SOCK:?the inventory carries no SSH key}"

inventory="${PWD}/$1"
if [ ! -f "${inventory}" ]; then
	echo "deploy.sh: the inventory repository holds no $1" >&2
	exit 2
fi

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
password_file="${workdir}/vault-password"
(umask 077 && printf '%s' "${DEPLOY_VAULT_PASSWORD}" >"${password_file}")
chmod 0400 "${password_file}"
unset DEPLOY_VAULT_PASSWORD

if [ -n "${DEPLOY_KNOWN_HOSTS}" ]; then
	printf '%s\n' "${DEPLOY_KNOWN_HOSTS}" >"${workdir}/known_hosts"
	export ANSIBLE_SSH_COMMON_ARGS="-o UserKnownHostsFile=${workdir}/known_hosts"
fi
install -d -m 0700 "${HOME}/.ssh"

infinito administration deploy dedicated "${inventory}" \
	--password-file "${password_file}" \
	--skip-build \
	-u "${DEPLOY_LOGIN}"
