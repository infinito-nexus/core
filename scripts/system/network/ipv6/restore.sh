#!/usr/bin/env bash
set -euo pipefail

STATE_FILE="/tmp/infinito-dev-environment-ipv6.state"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
	echo "[ipv6] error: restore.sh must be run as root (for example via 'sudo' or 'make network-ipv6-restore')" >&2
	exit 1
fi

restore_existing_interfaces() {
	local iface
	local value

	if ! declare -p IFACE_DISABLE_IPV6 >/dev/null 2>&1; then
		return 0
	fi

	for iface in "${!IFACE_DISABLE_IPV6[@]}"; do
		[[ "${iface}" == "all" || "${iface}" == "default" ]] && continue
		value="${IFACE_DISABLE_IPV6[${iface}]}"

		if ! sysctl -w "net.ipv6.conf.${iface}.disable_ipv6=${value}" >/dev/null 2>&1; then
			echo "[ipv6] warning: cannot restore net.ipv6.conf.${iface}.disable_ipv6"
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
	echo "[ipv6] skipping restore: sysctl is unavailable in this environment"
	exit 0
fi

if [[ ! -f "${STATE_FILE}" ]]; then
	echo "[ipv6] no saved state found; skipping restore"
	exit 0
fi

# shellcheck disable=SC1090
source "${STATE_FILE}"

: "${ALL_DISABLE_IPV6:?Missing ALL_DISABLE_IPV6 in ${STATE_FILE}}"
: "${DEFAULT_DISABLE_IPV6:?Missing DEFAULT_DISABLE_IPV6 in ${STATE_FILE}}"

if ! current_all="$(sysctl -n net.ipv6.conf.all.disable_ipv6 2>/dev/null)"; then
	echo "[ipv6] skipping restore: kernel does not expose net.ipv6.conf.all.disable_ipv6"
	exit 0
fi

if ! current_default="$(sysctl -n net.ipv6.conf.default.disable_ipv6 2>/dev/null)"; then
	echo "[ipv6] skipping restore: kernel does not expose net.ipv6.conf.default.disable_ipv6"
	exit 0
fi

echo "[ipv6] current: all=${current_all} default=${current_default}"
echo "[ipv6] restoring: all=${ALL_DISABLE_IPV6} default=${DEFAULT_DISABLE_IPV6}"

if ! sysctl -w "net.ipv6.conf.all.disable_ipv6=${ALL_DISABLE_IPV6}" >/dev/null; then
	echo "[ipv6] skipping restore: cannot update net.ipv6.conf.all.disable_ipv6"
	exit 0
fi

if ! sysctl -w "net.ipv6.conf.default.disable_ipv6=${DEFAULT_DISABLE_IPV6}" >/dev/null; then
	if ! sysctl -w "net.ipv6.conf.all.disable_ipv6=${current_all}" >/dev/null 2>&1; then
		echo "[ipv6] warning: failed to restore net.ipv6.conf.all.disable_ipv6"
	fi
	echo "[ipv6] skipping restore: cannot update net.ipv6.conf.default.disable_ipv6"
	exit 0
fi

restore_existing_interfaces
restart_docker_service

rm -f "${STATE_FILE}"

echo "[ipv6] restored for all, default, and currently existing interfaces"
echo "[ipv6] note: make network-ipv6-restore calls make network-refresh after the docker.service restart"
