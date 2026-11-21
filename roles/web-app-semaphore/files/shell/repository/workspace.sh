#!/usr/bin/env bash
# Env of the survey:
#   WORKSPACE               the workspace id, a lowercase UUID the store chose
#   WORKSPACE_ACTION        apply or destroy
#   WORKSPACE_CORE_VERSION  apply only: a released version like 17.0.0, or latest
#   WORKSPACE_TARGETS       apply only: comma-separated <host>:<port> pairs, empty
#                           for a workspace without servers
#   WORKSPACE_PLATFORM_TOKENS  apply only: true or false, whether the provider roles
#                              of the workspace may read the platform secrets
#
# Env of the Workspaces project (the deploy project's inventory, key and environment):
#   DEPLOY_VAULT_PASSWORD      vault password of the platform inventory, a Semaphore secret
#   DEPLOY_LOGIN               account the operation signs in to every platform host as
#   DEPLOY_KNOWN_HOSTS         known_hosts lines pinning the platform host keys
#   WORKSPACE_INVENTORY_FILE   the inventory file of the platform inventory checkout
#   WORKSPACE_PRIVATE_TARGETS  JSON list of the networks a target may lie in beside public ones
#   SSH_AUTH_SOCK              agent holding the deploy key
#   BAO_ADDR, BAO_CACERT       the OpenBao the pre-flight of the inventory's references logs in to
#   BAO_FIXTURE_ROLE           the jwt role workspace-fixture while the deploy fixture is on, else empty
#   SEMAPHORE_JWT              the task token Semaphore hands every task
#   INFINITO_SRC_DIR           the core tree of the runner image
set -euo pipefail

SCRIPT="workspace.sh"
here="$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=SCRIPTDIR/lib.sh
source "${here}/lib.sh"

refuse_arguments 0 "$@"

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
python3 "${here}/../../python/workspace.py" operation "${workdir}/result.json" >"${workdir}/operation.json"

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

echo "${SCRIPT}: ${WORKSPACE_ACTION} ws-${WORKSPACE}"
preflight="$(realpath "${here}/../../python/bao/preflight.py")"
(
	cd "${INFINITO_SRC_DIR:?the runner image names no core tree}"
	BAO_ROLE="${BAO_FIXTURE_ROLE-}" python3 "${preflight}" "${inventory}" \
		ansible-playbook -i "${inventory}" playbook-workspace.yml \
		--vault-password-file "${password_file}" \
		-u "${DEPLOY_LOGIN}" \
		-e "@${workdir}/operation.json"
)
python3 "${here}/../../python/workspace.py" result "${workdir}/operation.json" "${workdir}/result.json"
