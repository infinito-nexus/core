#!/usr/bin/env bash
# shellcheck shell=bash
#
# Expects from test.sh: BULK_BYTES, PING_COUNT, SSH_TIMEOUT, PYTHON,
# REPO_ROOT, DIR and INV, the inventory of the running scenario, and on()
# from lib/hosts.sh.

SSH_ARGS=()

repo_python() {
	PYTHONPATH="${REPO_ROOT}" "${PYTHON}" "$@"
}

mesh_helper() {
	repo_python "${DIR}/mesh.py" "$@"
}

load_mesh_ssh_args() {
	mapfile -t SSH_ARGS < <(mesh_helper ssh-args)
	SSH_ARGS+=(-o BatchMode=yes -o "ConnectTimeout=${SSH_TIMEOUT}")
}

address() {
	mesh_helper address "${INV}/host_vars" "$1" "$2"
}

conf_has() {
	on "$1" grep -q -E "$3" "/etc/wireguard/$2.conf"
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
