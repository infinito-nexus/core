#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/system/network/dns/common.sh
source "${SCRIPT_DIR}/common.sh"

echo ">>> Removing local DNS for *.${DNS_DOMAIN}"
echo ">>> Removing /etc/hosts fallback entries (if present)"
dns_remove_hosts_fallback

if ! dns_systemd_is_operational; then
	echo ">>> Skipping local DNS removal via systemd services: systemd service management is unavailable in this environment."
	echo ">>> Removed."
	exit 0
fi

# Remove NetworkManager dnsmasq setup
if systemctl is-active --quiet NetworkManager 2>/dev/null; then
	echo ">>> NetworkManager active -> removing NM dnsmasq config"
	sudo rm -f "${DNS_NM_CONF}" "${DNS_NM_DNSMASQ_CONF}"
	sudo systemctl restart NetworkManager
fi

# Remove system dnsmasq snippet (fallback setup)
sudo rm -f "${DNS_SYS_DNSMASQ_CONF}" || true

# If system dnsmasq is active, restart to apply
if systemctl is-active --quiet dnsmasq 2>/dev/null; then
	sudo systemctl restart dnsmasq || true
fi

# Remove the systemd-resolved routing drop-in (fallback setup)
if [[ -f "${DNS_RESOLVED_DROPIN}" ]]; then
	echo ">>> Removing systemd-resolved drop-in: ${DNS_RESOLVED_DROPIN}"
	sudo rm -f "${DNS_RESOLVED_DROPIN}"
	if systemctl is-active --quiet systemd-resolved 2>/dev/null; then
		sudo systemctl restart systemd-resolved || true
	fi
fi

echo ">>> Removed."
