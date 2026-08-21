#!/usr/bin/env bash
#
# Install OS-level dependencies required by the Claude Code sandbox.
#
# Installs `bubblewrap` (bwrap) and `socat`, which the sandbox backend
# needs to confine agent-launched commands. See:
#   docs/contributing/tools/agents/claude/sandbox.md
#
# Supported distributions:
#   - Debian / Ubuntu       (apt-get)
#   - Fedora                (dnf)
#   - CentOS / RHEL         (dnf or yum)
#   - Arch Linux            (pacman)
#
set -euo pipefail

PACKAGES=(bubblewrap socat)

run_privileged() {
	if [[ $EUID -eq 0 ]]; then
		"$@"
	elif command -v sudo >/dev/null 2>&1; then
		sudo "$@"
	else
		echo "[sandbox-deps] ERROR: need root or sudo to install packages" >&2
		exit 1
	fi
}

detect_distro_id() {
	if [[ -r /etc/os-release ]]; then
		# shellcheck disable=SC1091
		. /etc/os-release
		echo "${ID:-unknown}"
	else
		echo "unknown"
	fi
}

install_apt() {
	echo "[sandbox-deps] Installing via apt-get: ${PACKAGES[*]}"
	export DEBIAN_FRONTEND=noninteractive
	run_privileged apt-get update
	run_privileged apt-get install -y --no-install-recommends "${PACKAGES[@]}"
}

install_dnf() {
	echo "[sandbox-deps] Installing via dnf: ${PACKAGES[*]}"
	run_privileged dnf -y install "${PACKAGES[@]}"
}

install_yum() {
	echo "[sandbox-deps] Installing via yum: ${PACKAGES[*]}"
	run_privileged yum -y install "${PACKAGES[@]}"
}

install_pacman() {
	echo "[sandbox-deps] Installing via pacman: ${PACKAGES[*]}"
	run_privileged pacman -Sy --noconfirm --needed "${PACKAGES[@]}"
}

main() {
	local id
	id="$(detect_distro_id)"
	echo "[sandbox-deps] Detected distribution: ${id}"

	case "${id}" in
	debian | ubuntu | linuxmint | pop | raspbian)
		install_apt
		;;
	fedora)
		install_dnf
		;;
	centos | rhel | rocky | almalinux)
		if command -v dnf >/dev/null 2>&1; then
			install_dnf
		else
			install_yum
		fi
		;;
	arch | manjaro | endeavouros)
		install_pacman
		;;
	*)
		if command -v apt-get >/dev/null 2>&1; then
			install_apt
		elif command -v dnf >/dev/null 2>&1; then
			install_dnf
		elif command -v yum >/dev/null 2>&1; then
			install_yum
		elif command -v pacman >/dev/null 2>&1; then
			install_pacman
		else
			echo "[sandbox-deps] ERROR: unsupported distribution '${id}' and no known package manager found" >&2
			exit 1
		fi
		;;
	esac

	echo "[sandbox-deps] Verifying installed binaries..."
	for bin in bwrap socat; do
		if ! command -v "${bin}" >/dev/null 2>&1; then
			echo "[sandbox-deps] ERROR: '${bin}' not found on PATH after install" >&2
			exit 1
		fi
		printf '[sandbox-deps]   %s -> %s\n' "${bin}" "$(command -v "${bin}")"
	done

	echo "[sandbox-deps] Done."
}

main "$@"
