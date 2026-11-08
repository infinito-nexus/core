#!/usr/bin/env bash
# shellcheck shell=bash
#
# Env (all required; the role's test.env carries them):
#   BULK_BYTES   size of the transfer each reachable pair must carry intact
#   MESH_ROLE    role whose networks.meshes puts each host into its meshes
#   PING_COUNT   echo requests per reachability probe
#   PYTHON       interpreter that runs Ansible and the mesh CLI
#   REPO_ROOT    repository the deploy runs from
#   SSH_TIMEOUT  seconds an SSH connection may take before it counts as failed

set -euo pipefail

BULK_BYTES="${BULK_BYTES:?pass BULK_BYTES as env (bytes each reachable pair must carry)}"
MESH_ROLE="${MESH_ROLE:?pass MESH_ROLE as env (role whose networks.meshes joins the hosts)}"
PING_COUNT="${PING_COUNT:?pass PING_COUNT as env (echo requests per probe)}"
PYTHON="${PYTHON:?pass PYTHON as env (interpreter that runs Ansible)}"
REPO_ROOT="${REPO_ROOT:?pass REPO_ROOT as env (repository the deploy runs from)}"
SSH_TIMEOUT="${SSH_TIMEOUT:?pass SSH_TIMEOUT as env (seconds an SSH connection may take)}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${DIR}/compose.yml"
PREFIX="wg-mesh-$$"
NETWORK="${PREFIX}"
HOST_I="${PREFIX}-1"
HOST_II="${PREFIX}-2"
HOST_III="${PREFIX}-3"
HOSTS=("${HOST_I}" "${HOST_II}" "${HOST_III}")
WORK="$(mktemp -d)"

# shellcheck source=roles/svc-net-wireguard/files/test/lib/hosts.sh
source "${DIR}/lib/hosts.sh"
# shellcheck source=roles/svc-net-wireguard/files/test/lib/probes.sh
source "${DIR}/lib/probes.sh"
# shellcheck source=roles/svc-net-wireguard/files/test/lib/checks.sh
source "${DIR}/lib/checks.sh"

cleanup() {
	hosts_compose down --remove-orphans >/dev/null 2>&1
	rm -rf "${WORK}"
}
trap cleanup EXIT

cd "${REPO_ROOT}"
"${PYTHON}" -c 'import secrets; print(secrets.token_hex(32))' >"${WORK}/.password"
load_mesh_ssh_args

echo "[INFO] starting three throwaway hosts from $(hosts_compose config --images | sort -u)"
hosts_compose up --detach --quiet-pull >/dev/null
for host in "${HOSTS[@]}"; do
	provision_host "${host}"
done
authorize_every_host

write_layout() {
	local layout="$1"
	echo "[INFO] writing the inventory of the layout in ${layout}"
	repo_python "${DIR}/inventory.py" "${layout}" "${INV}" "${MESH_ROLE}" \
		"I=${HOST_I}" "II=${HOST_II}" "III=${HOST_III}"
	echo "[INFO] writing the meshes into the inventory"
	"${PYTHON}" -m cli.administration.inventory.mesh \
		--inventory "${INV}/devices.yml" \
		--host-vars-dir "${INV}/host_vars" \
		--vault-password-file "${WORK}/.password"
}

deploy_mesh() {
	local hosts="$1"
	echo "[INFO] deploying svc-net-wireguard onto ${hosts}"
	"$(dirname "${PYTHON}")/ansible-playbook" \
		-i "${INV}/devices.yml" \
		--vault-password-file "${WORK}/.password" \
		--limit "${hosts}" \
		playbooks/lab/mesh.yml
}

INV="${WORK}/full"
write_layout "${DIR}/layout.yml"
deploy_mesh "${HOST_I},${HOST_II},${HOST_III}"

expect_reach "${HOST_I}" "${HOST_II}" alpha
expect_reach "${HOST_II}" "${HOST_I}" alpha
expect_reach "${HOST_II}" "${HOST_III}" beta
expect_reach "${HOST_III}" "${HOST_II}" beta
expect_isolated "${HOST_I}" "${HOST_III}" beta alpha
expect_isolated "${HOST_III}" "${HOST_I}" alpha beta

INV="${WORK}/hub"
write_layout "${DIR}/layout-hub.yml"
deploy_mesh "${HOST_I},${HOST_III}"
deploy_mesh "${HOST_II}"

expect_roaming "${HOST_I}" "${HOST_II}" gamma 51902
expect_reach "${HOST_II}" "${HOST_III}" gamma
expect_reach "${HOST_III}" "${HOST_II}" gamma

if ((failures > 0)); then
	echo "[FATAL] ${failures} mesh assertion(s) failed" >&2
	exit 1
fi
echo "[OK] full meshes: I and II reach each other, II and III reach each other, I and III do not"
echo "[OK] hub I: it deployed without the roaming II, and II and III reach each other through it"
