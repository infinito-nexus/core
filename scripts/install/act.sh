#!/usr/bin/env bash
# Provision act (nektos/act) for the act-based make targets. Installs the
# static release binary on demand (idempotent); pass `update` to force the
# latest. Distro-independent: needs only curl-or-wget plus tar.
set -euo pipefail

mode="${1:-install}"

if [ "${mode}" != "update" ] && command -v act >/dev/null 2>&1; then
	exit 0
fi

bin_dir="${ACT_INSTALL_DIR:-/usr/local/bin}" # nocheck: installer-local target dir, runs before default.env exists
sudo=""
[ -w "${bin_dir}" ] || sudo="sudo"

case "$(uname -m)" in
x86_64) asset="act_Linux_x86_64.tar.gz" ;;
aarch64 | arm64) asset="act_Linux_arm64.tar.gz" ;;
*)
	echo "[install-act] unsupported architecture: $(uname -m)" >&2
	exit 1
	;;
esac

fetch() {
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL "$1"
	elif command -v wget >/dev/null 2>&1; then
		wget -qO- "$1"
	else
		echo "[install-act] curl or wget is required to install act" >&2
		exit 1
	fi
}

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

echo "[install-act] installing act (${asset}) into ${bin_dir}"
fetch "https://github.com/nektos/act/releases/latest/download/${asset}" >"${tmp}/act.tgz"
tar -xzf "${tmp}/act.tgz" -C "${tmp}" act
${sudo} install -m 0755 "${tmp}/act" "${bin_dir}/act"

echo "[install-act] installed: $("${bin_dir}/act" --version 2>/dev/null || echo 'version check failed')"
