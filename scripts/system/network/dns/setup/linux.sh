#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/system/network/dns/common.sh
source "${SCRIPT_DIR}/../common.sh"

echo ">>> Setting up local DNS for *.${DNS_DOMAIN} -> 127.0.0.1"

configure_via_hosts_file() {
	echo ">>> Non-systemd environment detected -> configuring /etc/hosts fallback"
	echo ">>> Hosts file: ${DNS_HOSTS_FILE}"
	echo ">>> Host entries:"
	dns_read_hosts_fallback_entries | sed 's/^/    /'

	dns_write_hosts_fallback
	dns_test_resolution

	echo
	echo ">>> Local DNS fallback configured for:"
	dns_read_hosts_fallback_entries | sed 's/^/    /'
}

install_dnsmasq_if_missing() {
	if command -v dnsmasq >/dev/null 2>&1; then
		return 0
	fi

	echo ">>> dnsmasq not found -> installing"

	if command -v pacman >/dev/null 2>&1; then
		sudo pacman -S --noconfirm --needed dnsmasq
	elif command -v apt-get >/dev/null 2>&1; then
		sudo apt-get update
		sudo apt-get install -y dnsmasq
	elif command -v dnf >/dev/null 2>&1; then
		sudo dnf install -y dnsmasq
	else
		echo "ERROR: Unsupported distro/package manager. Install dnsmasq manually."
		exit 1
	fi
}

if ! dns_systemd_is_operational; then
	echo ">>> Skipping local DNS setup via systemd services: systemd service management is unavailable in this environment."
	configure_via_hosts_file
	exit 0
fi

configure_via_networkmanager_dnsmasq() {
	echo ">>> Detected NetworkManager -> configuring NM dnsmasq plugin (recommended)"
	install_dnsmasq_if_missing

	# Avoid port conflicts with a system-wide dnsmasq service
	if systemctl is-enabled --quiet dnsmasq 2>/dev/null || systemctl is-active --quiet dnsmasq 2>/dev/null; then
		echo ">>> Disabling system dnsmasq to avoid conflicts with NetworkManager dnsmasq"
		sudo systemctl disable --now dnsmasq || true
	fi

	echo ">>> Writing NetworkManager dnsmasq config: ${DNS_NM_CONF}"
	sudo mkdir -p "$(dirname "${DNS_NM_CONF}")"
	cat <<EOF | sudo tee "${DNS_NM_CONF}" >/dev/null
[main]
dns=dnsmasq
EOF

	echo ">>> Writing dnsmasq snippet for NetworkManager: ${DNS_NM_DNSMASQ_CONF}"
	sudo mkdir -p "${DNS_NM_DNSMASQ_DIR}"
	cat <<EOF | sudo tee "${DNS_NM_DNSMASQ_CONF}" >/dev/null
# Map the entire zone to localhost (wildcard)
address=/${DNS_DOMAIN}/127.0.0.1
address=/${DNS_DOMAIN}/::1
EOF

	echo ">>> Restarting NetworkManager"
	sudo systemctl restart NetworkManager

	echo ">>> Resolver status"
	cat /etc/resolv.conf || true
}

configure_via_system_dnsmasq() {
	echo ">>> NetworkManager not active -> configuring system dnsmasq (fallback)"
	install_dnsmasq_if_missing

	echo ">>> Writing system dnsmasq config: ${DNS_SYS_DNSMASQ_CONF}"
	sudo mkdir -p /etc/dnsmasq.d
	cat <<EOF | sudo tee "${DNS_SYS_DNSMASQ_CONF}" >/dev/null
address=/${DNS_DOMAIN}/127.0.0.1
address=/${DNS_DOMAIN}/::1
EOF

	echo ">>> Enabling and restarting dnsmasq service"
	sudo systemctl enable dnsmasq --now
	sudo systemctl restart dnsmasq

	# systemd-resolved rejects per-link DNS on loopback, so route the zone to
	# dnsmasq via a global drop-in instead of `resolvectl dns lo ...`.
	if systemctl is-active --quiet systemd-resolved 2>/dev/null; then
		echo ">>> Routing ${DNS_DOMAIN} to dnsmasq via systemd-resolved drop-in: ${DNS_RESOLVED_DROPIN}"
		sudo mkdir -p "$(dirname "${DNS_RESOLVED_DROPIN}")"
		cat <<EOF | sudo tee "${DNS_RESOLVED_DROPIN}" >/dev/null
# Managed by infinito-nexus (make network-dns-remove) — routes ${DNS_DOMAIN} to local dnsmasq.
[Resolve]
DNS=127.0.0.1
Domains=~${DNS_DOMAIN}
EOF
		sudo systemctl restart systemd-resolved
	else
		echo ">>> systemd-resolved not active -> skipping resolved integration"
		echo ">>> NOTE: Ensure your system resolver uses 127.0.0.1 to query dnsmasq."
	fi
}

# Prefer NetworkManager path if NM is present+active (your case)
if systemctl is-active --quiet NetworkManager 2>/dev/null; then
	configure_via_networkmanager_dnsmasq
else
	configure_via_system_dnsmasq
fi

dns_test_resolution

echo
echo ">>> Local DNS configured for:"
echo "    ${DNS_DOMAIN}"
echo "    *.${DNS_DOMAIN}"
