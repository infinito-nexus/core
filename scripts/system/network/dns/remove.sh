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

if systemctl is-active --quiet NetworkManager 2>/dev/null; then
	echo ">>> NetworkManager active -> removing NM dnsmasq config"
	sudo rm -f "${DNS_NM_CONF}" "${DNS_NM_DNSMASQ_CONF}"
	sudo systemctl restart NetworkManager
fi

sudo rm -f "${DNS_SYS_DNSMASQ_CONF}" || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

if systemctl is-active --quiet dnsmasq 2>/dev/null; then
	sudo systemctl restart dnsmasq || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

if [[ -f "${DNS_RESOLVED_DROPIN}" ]]; then
	echo ">>> Removing systemd-resolved drop-in: ${DNS_RESOLVED_DROPIN}"
	sudo rm -f "${DNS_RESOLVED_DROPIN}"
	if systemctl is-active --quiet systemd-resolved 2>/dev/null; then
		sudo systemctl restart systemd-resolved || true # nocheck: shell-or-true -- teardown: the drop-in is already deleted, so the zone is unrouted whether or not resolved comes back; aborting here would skip the rest of the cleanup over a restart this script does not own.
	fi
fi

echo ">>> Removed."
