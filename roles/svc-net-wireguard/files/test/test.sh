#!/usr/bin/env bash
# shellcheck shell=bash
#
# svc-net-wireguard role test: three throwaway hosts in two full meshes.
#
# Env (all required; the role's test.env carries them):
#   BULK_BYTES   size of the transfer each reachable pair must carry intact
#   HOST_IMAGE   pinned base image of the throwaway hosts, without WireGuard
#   MESH_ROLE    role whose networks.meshes puts each host into its meshes
#   PING_COUNT   echo requests per reachability probe
#   PYTHON       interpreter that runs Ansible and the mesh CLI
#   REPO_ROOT    repository the deploy runs from
#   SSH_TIMEOUT  seconds an SSH connection may take before it counts as failed

set -euo pipefail

BULK_BYTES="${BULK_BYTES:?pass BULK_BYTES as env (bytes each reachable pair must carry)}"
HOST_IMAGE="${HOST_IMAGE:?pass HOST_IMAGE as env (pinned base image of the hosts)}"
MESH_ROLE="${MESH_ROLE:?pass MESH_ROLE as env (role whose networks.meshes joins the hosts)}"
PING_COUNT="${PING_COUNT:?pass PING_COUNT as env (echo requests per probe)}"
PYTHON="${PYTHON:?pass PYTHON as env (interpreter that runs Ansible)}"
REPO_ROOT="${REPO_ROOT:?pass REPO_ROOT as env (repository the deploy runs from)}"
SSH_TIMEOUT="${SSH_TIMEOUT:?pass SSH_TIMEOUT as env (seconds an SSH connection may take)}"

PREFIX="wg-mesh-$$"
NETWORK="${PREFIX}"
HOST_I="${PREFIX}-1"
HOST_II="${PREFIX}-2"
HOST_III="${PREFIX}-3"
HOSTS=("${HOST_I}" "${HOST_II}" "${HOST_III}")
WORK="$(mktemp -d)"
SSH_ARGS=()
failures=0

cleanup() {
	local host
	for host in "${HOSTS[@]}"; do
		if container inspect --type container "${host}" >/dev/null 2>&1; then
			container rm -f "${host}" >/dev/null
		fi
	done
	if container network inspect "${NETWORK}" >/dev/null 2>&1; then
		container network rm "${NETWORK}" >/dev/null
	fi
	rm -rf "${WORK}"
}
trap cleanup EXIT

on() {
	local host="$1"
	shift
	container exec "${host}" "$@"
}

start_host() {
	local host="$1"
	container run --detach --name "${host}" --hostname "${host}" \
		--network "${NETWORK}" --cap-add NET_ADMIN \
		"${HOST_IMAGE}" sleep infinity >/dev/null
	on "${host}" sh -c 'rm -rf /var/lib/apt/lists/* \
		&& apt-get -o Acquire::Retries=3 update -qq \
		&& apt-get -o Acquire::Retries=3 install -y -qq --no-install-recommends \
			python3 openssh-server \
		&& mkdir -p /run/sshd /root/.ssh \
		&& chmod 700 /root/.ssh \
		&& ssh-keygen -q -t ed25519 -N "" -f /root/.ssh/id_ed25519 \
		&& /usr/sbin/sshd' >/dev/null
}

authorize_every_host() {
	local host keys=""
	for host in "${HOSTS[@]}"; do
		keys+="$(on "${host}" cat /root/.ssh/id_ed25519.pub)"$'\n'
	done
	for host in "${HOSTS[@]}"; do
		printf '%s' "${keys}" | container exec -i "${host}" \
			sh -c 'cat >/root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys'
	done
}

host_vars() {
	local host="$1" meshes="$2"
	cat >"${WORK}/host_vars/${host}.yml" <<EOF
ansible_connection: docker
ansible_host: ${host}
ansible_user: root
ansible_python_interpreter: /usr/bin/python3
applications:
  svc-net-wireguard:
    networks:
      meshes:
        - name: alpha
          subnet: "10.100.200.0/24"
          listen_port: 51900
        - name: beta
          subnet: "10.100.201.0/24"
          listen_port: 51901
  ${MESH_ROLE}:
    networks:
      meshes: ${meshes}
EOF
}

address() {
	"${PYTHON}" - "${WORK}/host_vars" "$1" "$2" <<'EOF'
import sys
from pathlib import Path

from cli.administration.inventory.mesh.transport import mesh_address

print(mesh_address(Path(sys.argv[1]), sys.argv[2], sys.argv[3]) or "")
EOF
}

load_mesh_ssh_args() {
	mapfile -t SSH_ARGS < <("${PYTHON}" - <<'EOF'
import shlex

from cli.administration.inventory.mesh.transport import mesh_ssh_args, repo_ssh_args

print("\n".join(shlex.split(mesh_ssh_args(repo_ssh_args()))))
EOF
	)
	SSH_ARGS+=(-o BatchMode=yes -o "ConnectTimeout=${SSH_TIMEOUT}")
}

check() {
	local description="$1"
	shift
	if "$@"; then
		echo "[PASS] ${description}"
	else
		echo "[FAIL] ${description}" >&2
		failures=$((failures + 1))
	fi
}

not() {
	! "$@"
}

pings() {
	on "$1" ping -c "${PING_COUNT}" -W 2 "$2" >/dev/null 2>&1
}

ssh_to() {
	local from="$1" target="$2"
	shift 2
	on "${from}" ssh -n "${SSH_ARGS[@]}" "root@${target}" "$@"
}

lands_on() {
	[[ "$(ssh_to "$1" "$2" cat /etc/hostname 2>/dev/null)" == "$3" ]]
}

carries_bulk() {
	local from="$1" to="$2" target="$3" sent received
	sent="$(on "${to}" sh -c "head -c ${BULK_BYTES} /dev/urandom >/tmp/mesh-bulk && sha256sum </tmp/mesh-bulk")"
	received="$(ssh_to "${from}" "${target}" cat /tmp/mesh-bulk | sha256sum)"
	[[ -n "${sent}" && "${sent}" == "${received}" ]]
}

ssh_never_connects() {
	local output
	if output="$(ssh_to "$1" "$2" true 2>&1)"; then
		return 1
	fi
	[[ "${output}" != *"Permission denied"* ]]
}

refused_by_wireguard() {
	local from="$1" target="$2" via="$3" output
	on "${from}" ip route add "${target}/32" dev "${via}"
	output="$(on "${from}" ping -c 1 -W 2 "${target}" 2>&1)"
	on "${from}" ip route del "${target}/32" dev "${via}"
	[[ "${output}" == *"Required key not available"* ]]
}

expect_reach() {
	local from="$1" to="$2" mesh="$3" target
	target="$(address "${to}" "${mesh}")"
	if [[ -z "${target}" ]]; then
		check "${to} holds an address on ${mesh}" false
		return
	fi
	check "${from} pings ${to} at ${target} over ${mesh}" pings "${from}" "${target}"
	check "${from} opens SSH to ${target} over ${mesh} and lands on ${to}" lands_on "${from}" "${target}" "${to}"
	check "${from} pulls ${BULK_BYTES} bytes from ${to} over ${mesh} intact" carries_bulk "${from}" "${to}" "${target}"
}

expect_isolated() {
	local from="$1" to="$2" mesh="$3" via="$4" target
	target="$(address "${to}" "${mesh}")"
	if [[ -z "${target}" ]]; then
		check "${to} holds an address on ${mesh}" false
		return
	fi
	check "${from} does not ping ${to} at ${target} over ${mesh}" not pings "${from}" "${target}"
	check "${from} cannot open SSH to ${to} at ${target} over ${mesh}" ssh_never_connects "${from}" "${target}"
	check "WireGuard on ${from} refuses ${target} routed into ${via}" refused_by_wireguard "${from}" "${target}" "${via}"
	check "${from} still reaches ${to} on the underlay" pings "${from}" "${to}"
}

cd "${REPO_ROOT}"
mkdir -p "${WORK}/host_vars"
"${PYTHON}" -c 'import secrets; print(secrets.token_hex(32))' >"${WORK}/.password"
load_mesh_ssh_args

echo "[INFO] starting three throwaway hosts from ${HOST_IMAGE}"
container network create "${NETWORK}" >/dev/null
for host in "${HOSTS[@]}"; do
	start_host "${host}"
done
authorize_every_host

cat >"${WORK}/devices.yml" <<EOF
all:
  children:
    svc-net-wireguard:
      hosts:
        ${HOST_I}: {}
        ${HOST_II}: {}
        ${HOST_III}: {}
    ${MESH_ROLE}:
      hosts:
        ${HOST_I}: {}
        ${HOST_II}: {}
        ${HOST_III}: {}
EOF
host_vars "${HOST_I}" "[alpha]"
host_vars "${HOST_II}" "[alpha, beta]"
host_vars "${HOST_III}" "[beta]"

echo "[INFO] writing the meshes into the inventory"
"${PYTHON}" -m cli.administration.inventory.mesh \
	--inventory "${WORK}/devices.yml" \
	--host-vars-dir "${WORK}/host_vars" \
	--vault-password-file "${WORK}/.password"

echo "[INFO] deploying svc-net-wireguard onto the three hosts"
"$(dirname "${PYTHON}")/ansible-playbook" \
	-i "${WORK}/devices.yml" \
	--vault-password-file "${WORK}/.password" \
	playbooks/mesh.yml

expect_reach "${HOST_I}" "${HOST_II}" alpha
expect_reach "${HOST_II}" "${HOST_I}" alpha
expect_reach "${HOST_II}" "${HOST_III}" beta
expect_reach "${HOST_III}" "${HOST_II}" beta
expect_isolated "${HOST_I}" "${HOST_III}" beta alpha
expect_isolated "${HOST_III}" "${HOST_I}" alpha beta

if ((failures > 0)); then
	echo "[FATAL] ${failures} mesh assertion(s) failed" >&2
	exit 1
fi
echo "[OK] I and II reach each other, II and III reach each other, I and III do not"
