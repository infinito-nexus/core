#!/usr/bin/env bash
# shellcheck shell=bash
#
# Expects from test.sh: BULK_BYTES, and the probes from lib/probes.sh.

failures=0

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
