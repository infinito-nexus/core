#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/meta/env/load.sh
source "${SCRIPT_DIR}/../../../../meta/env/load.sh"
[[ "${INFINITO_IS_WSL2}" == "true" ]] || exit 0

UPSTREAM_CONF="/etc/dnsmasq.d/00-wsl2-upstream.conf"
STUB_CONF="/etc/systemd/resolved.conf.d/disable-stub.conf"
WSL_CONF="/etc/wsl.conf"
RESOLV_CONF="/etc/resolv.conf"

# Discover the WSL2 DNS gateway before we replace resolv.conf
UPSTREAM_DNS=$(grep -m1 "^nameserver" "${RESOLV_CONF}" 2>/dev/null | awk '{print $2}' || true)
if [[ -z "${UPSTREAM_DNS}" ]]; then
	UPSTREAM_DNS=$(ip route show default 2>/dev/null | awk '/default via/{print $3; exit}' || true)
fi
if [[ -z "${UPSTREAM_DNS}" ]]; then
	UPSTREAM_DNS="8.8.8.8" # nocheck: hardcoded-dns-resolver
fi

echo ">>> WSL2 DNS setup — upstream gateway: ${UPSTREAM_DNS}"

# Disable systemd-resolved stub listener to free port 53 for dnsmasq
if [[ ! -f "${STUB_CONF}" ]]; then
	echo ">>> Disabling systemd-resolved stub listener"
	sudo mkdir -p "$(dirname "${STUB_CONF}")"
	printf '[Resolve]\nDNSStubListener=no\n' | sudo tee "${STUB_CONF}" >/dev/null
	sudo systemctl restart systemd-resolved
fi

# Tell dnsmasq to forward unknown queries to the WSL2 DNS gateway
echo ">>> Writing dnsmasq upstream forwarder: ${UPSTREAM_CONF}"
printf 'server=%s\n' "${UPSTREAM_DNS}" | sudo tee "${UPSTREAM_CONF}" >/dev/null

# Disable WSL auto-generation of resolv.conf
if ! grep -qs "generateResolvConf\s*=\s*false" "${WSL_CONF}" 2>/dev/null; then
	echo ">>> Disabling WSL auto-generation of /etc/resolv.conf"
	if grep -qs "^\[network\]" "${WSL_CONF}" 2>/dev/null; then
		sudo sed -i '/^\[network\]/a generateResolvConf = false' "${WSL_CONF}"
	else
		printf '\n[network]\ngenerateResolvConf = false\n' | sudo tee -a "${WSL_CONF}" >/dev/null
	fi
fi

# Point resolv.conf at dnsmasq
echo ">>> Pointing /etc/resolv.conf at 127.0.0.1 (dnsmasq)"
sudo rm -f "${RESOLV_CONF}"
printf 'nameserver 127.0.0.1\n' | sudo tee "${RESOLV_CONF}" >/dev/null

echo ">>> Restarting dnsmasq"
sudo systemctl enable dnsmasq --quiet 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
sudo systemctl restart dnsmasq

# Register WSL interop binfmt handler so Windows .exe files can be executed from WSL
# Required for tools like powershell.exe when appendWindowsPath=false
BINFMT_CONF="/etc/binfmt.d/WSLInterop.conf"
if [[ ! -f "${BINFMT_CONF}" ]]; then
	echo ">>> Registering WSL interop binfmt handler"
	printf ':WSLInterop:M::MZ::/init:PF\n' | sudo tee "${BINFMT_CONF}" >/dev/null
	sudo systemctl restart systemd-binfmt
fi
if ! grep -qs "WSLInterop" /proc/sys/fs/binfmt_misc/WSLInterop 2>/dev/null; then
	printf ':WSLInterop:M::MZ::/init:PF\n' | sudo tee /proc/sys/fs/binfmt_misc/register >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

echo ">>> WSL2 DNS pre-configuration complete"
