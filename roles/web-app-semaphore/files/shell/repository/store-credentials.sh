#!/usr/bin/env bash
# Env of the Workspaces project (the deploy project's inventory, key and environment):
#   DEPLOY_VAULT_PASSWORD       vault password of the platform inventory, a Semaphore secret
#   DEPLOY_LOGIN                account the playbook signs in to every platform host as
#   DEPLOY_KNOWN_HOSTS          known_hosts lines pinning the platform host keys
#   WORKSPACE_INVENTORY_FILE    the inventory file of the platform inventory checkout
#   SSH_AUTH_SOCK               agent holding the deploy key
#   BAO_ADDR, BAO_CACERT        the OpenBao the entries go to
#   BAO_STORE_CREDENTIALS_ROLE  the task token role of rotate store credentials
#   SEMAPHORE_JWT               the task token Semaphore hands every task
#   SEMAPHORE_STORE_USERNAME, SEMAPHORE_DB_HOST, SEMAPHORE_DB_PORT, SEMAPHORE_DB,
#   SEMAPHORE_DB_USER, SEMAPHORE_DB_PASS  the Semaphore side
#   INFINITO_SRC_DIR            the core tree of the runner image
set -euo pipefail

SCRIPT="store-credentials.sh"
here="$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib.sh
source "${here}/lib.sh"

refuse_arguments 0 "$@"

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

: "${DEPLOY_VAULT_PASSWORD:?the project environment carries no vault password}"
: "${DEPLOY_LOGIN:?the project environment names no login}"
: "${DEPLOY_KNOWN_HOSTS?the project environment declares no known_hosts}"
: "${SSH_AUTH_SOCK:?the inventory carries no SSH key}"
inventory="$(workspace_inventory "${WORKSPACE_INVENTORY_FILE:?the project environment names no inventory file}")"
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
install -d -m 0700 "${HOME}/.ssh"

export BAO_TOKEN_FILE="${workdir}/bao-token"
BAO_ROLE="${BAO_STORE_CREDENTIALS_ROLE:?the project environment names no rotation role}" \
	python3 "${here}/../../python/bao/login.py" "${BAO_TOKEN_FILE}"
python3 "${here}/../../python/rotate_store_credentials.py" plan "${workdir}" >"${workdir}/plan.json"

echo "${SCRIPT}: minting the store's Gitea token"
(
	cd "${INFINITO_SRC_DIR:?the runner image names no core tree}"
	ansible-playbook -i "${inventory}" playbook-store-credentials.yml \
		--vault-password-file "${password_file}" \
		-u "${DEPLOY_LOGIN}" \
		-e "@${workdir}/plan.json" \
		-e MASK_CREDENTIALS_IN_LOGS=true
)
python3 "${here}/../../python/rotate_store_credentials.py" rotate "${workdir}/plan.json"
