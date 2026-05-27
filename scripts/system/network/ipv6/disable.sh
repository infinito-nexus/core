#!/usr/bin/env bash
set -euo pipefail

STATE_FILE="/tmp/infinito-dev-environment-ipv6.state"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
	echo "[ipv6] error: disable.sh must be run as root (for example via 'sudo' or 'make network-ipv6-disable')" >&2
	exit 1
fi

write_state_file() {
	local current_all="$1"
	local current_default="$2"
	local path
	local iface
	local value

	{
		printf 'ALL_DISABLE_IPV6=%q\n' "${current_all}"
		printf 'DEFAULT_DISABLE_IPV6=%q\n' "${current_default}"
		printf 'declare -A IFACE_DISABLE_IPV6=(\n'
		for path in /proc/sys/net/ipv6/conf/*/disable_ipv6; do
			[[ -e "${path}" ]] || continue
			iface="${path%/disable_ipv6}"
			iface="${iface##*/}"
			value="$(<"${path}")"
			printf '  [%q]=%q\n' "${iface}" "${value}"
		done
		printf ')\n'
	} >"${STATE_FILE}"
}

disable_existing_interfaces() {
	local path
	local iface

	for path in /proc/sys/net/ipv6/conf/*/disable_ipv6; do
		[[ -e "${path}" ]] || continue
		iface="${path%/disable_ipv6}"
		iface="${iface##*/}"
		[[ "${iface}" == "all" || "${iface}" == "default" ]] && continue

		if ! sysctl -w "net.ipv6.conf.${iface}.disable_ipv6=1" >/dev/null 2>&1; then
			echo "[ipv6] warning: cannot update net.ipv6.conf.${iface}.disable_ipv6"
		fi
	done
}

restart_docker_service() {
	if ! command -v systemctl >/dev/null 2>&1; then
		echo "[ipv6] warning: systemctl is unavailable; skipping docker.service restart"
		return 0
	fi

	if ! systemctl list-unit-files docker.service >/dev/null 2>&1; then
		echo "[ipv6] warning: docker.service is unavailable; skipping docker.service restart"
		return 0
	fi

	echo "[ipv6] restarting docker.service"
	if ! systemctl restart docker.service >/dev/null 2>&1; then
		echo "[ipv6] warning: failed to restart docker.service"
		return 0
	fi

	echo "[ipv6] restarted docker.service"
}

if ! command -v sysctl >/dev/null 2>&1; then
	echo "[ipv6] skipping disable: sysctl is unavailable in this environment"
	exit 0
fi

if ! current_all="$(sysctl -n net.ipv6.conf.all.disable_ipv6 2>/dev/null)"; then
	echo "[ipv6] skipping disable: kernel does not expose net.ipv6.conf.all.disable_ipv6"
	exit 0
fi

if ! current_default="$(sysctl -n net.ipv6.conf.default.disable_ipv6 2>/dev/null)"; then
	echo "[ipv6] skipping disable: kernel does not expose net.ipv6.conf.default.disable_ipv6"
	exit 0
fi

echo "[ipv6] current: all=${current_all} default=${current_default}"

if [[ ! -f "${STATE_FILE}" ]]; then
	write_state_file "${current_all}" "${current_default}"
else
	echo "[ipv6] existing state file found at ${STATE_FILE}; keeping original restore values"
fi

if ! sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null; then
	rm -f "${STATE_FILE}"
	echo "[ipv6] skipping disable: cannot update net.ipv6.conf.all.disable_ipv6"
	exit 0
fi

if ! sysctl -w net.ipv6.conf.default.disable_ipv6=1 >/dev/null; then
	if ! sysctl -w "net.ipv6.conf.all.disable_ipv6=${current_all}" >/dev/null 2>&1; then
		echo "[ipv6] warning: failed to restore net.ipv6.conf.all.disable_ipv6"
	fi
	rm -f "${STATE_FILE}"
	echo "[ipv6] skipping disable: cannot update net.ipv6.conf.default.disable_ipv6"
	exit 0
fi

disable_existing_interfaces
restart_docker_service

echo "[ipv6] disabled for all, default, and currently existing interfaces"
echo "[ipv6] note: make network-ipv6-disable calls make network-refresh after the docker.service restart"
