#!/usr/bin/env bash

DNS_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DNS_PROJECT_ROOT="$(cd "${DNS_SCRIPT_DIR}/../../../.." && pwd)"
DNS_DOMAIN="${INFINITO_DNS_DOMAIN}"
DNS_HOSTS_FILE="${INFINITO_DNS_HOSTS_FILE}"
DNS_HOSTS_BLOCK_BEGIN="# BEGIN infinito-dns-fallback"
DNS_HOSTS_BLOCK_END="# END infinito-dns-fallback"
DNS_HOSTS_GENERATOR="${DNS_PROJECT_ROOT}/cli/meta/domains/__main__.py"
DNS_HOSTS_FALLBACK_DEFAULT_RAW="${DNS_DOMAIN} dashboard.${DNS_DOMAIN} matomo.${DNS_DOMAIN}"

# Used by setup.sh/remove.sh after sourcing this shared helper.
# shellcheck disable=SC2034
DNS_NM_CONF="/etc/NetworkManager/conf.d/00-infinito-dnsmasq.conf"
DNS_NM_DNSMASQ_DIR="/etc/NetworkManager/dnsmasq.d"
# shellcheck disable=SC2034
DNS_NM_DNSMASQ_CONF="${DNS_NM_DNSMASQ_DIR}/${DNS_DOMAIN}.conf"
# shellcheck disable=SC2034
DNS_SYS_DNSMASQ_CONF="/etc/dnsmasq.d/${DNS_DOMAIN}.conf"
# shellcheck disable=SC2034
DNS_RESOLVED_DROPIN="/etc/systemd/resolved.conf.d/${DNS_DOMAIN}.conf"

dns_systemd_is_operational() {
	command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

dns_path_is_writable() {
	local path="$1"

	if [[ -e "${path}" ]]; then
		[[ -w "${path}" ]]
	else
		[[ -w "$(dirname "${path}")" ]]
	fi
}

dns_run_with_optional_sudo() {
	if [[ "$(id -u)" -eq 0 ]] || dns_path_is_writable "${DNS_HOSTS_FILE}"; then
		"$@"
	else
		sudo "$@"
	fi
}

dns_write_file_in_place() {
	local src="$1"
	local dest="$2"

	if [[ "$(id -u)" -eq 0 ]] || dns_path_is_writable "${dest}"; then
		cat "${src}" >"${dest}"
	else
		sudo dd if="${src}" of="${dest}" status=none
	fi
}

dns_normalize_hosts_entries() {
	tr ',[:space:]' '\n' | awk 'NF && !seen[$0]++'
}

dns_read_hosts_fallback_entries_from_raw() {
	local raw="$1"

	printf '%s\n' "${raw}" | dns_normalize_hosts_entries
}

dns_read_generated_hosts_fallback_entries() {
	local output

	if ! command -v python3 >/dev/null 2>&1 || [[ ! -f "${DNS_HOSTS_GENERATOR}" ]]; then
		return 1
	fi

	if ! output="$(
		DOMAIN="${DNS_DOMAIN}" PYTHONPATH="${DNS_PROJECT_ROOT}" python3 -m cli.meta.domains --domain-primary "${DNS_DOMAIN}" --alias --www
	)"; then
		echo ">>> Failed to generate DNS hosts from role configs; using static fallback." >&2
		return 1
	fi

	if [[ -z "${output//[[:space:]]/}" ]]; then
		echo ">>> DNS host generator returned no entries; using static fallback." >&2
		return 1
	fi

	printf '%s\n' "${output}" | dns_normalize_hosts_entries
}

dns_read_hosts_fallback_entries() {
	if [[ -n "${INFINITO_DNS_HOSTS:-}" ]]; then                       # nocheck: infinito-dns-hosts-optional
		dns_read_hosts_fallback_entries_from_raw "${INFINITO_DNS_HOSTS}" # nocheck: infinito-dns-hosts-optional
		return
	fi

	if dns_read_generated_hosts_fallback_entries; then
		return
	fi

	dns_read_hosts_fallback_entries_from_raw "${DNS_HOSTS_FALLBACK_DEFAULT_RAW}"
}

dns_rewrite_hosts_file() {
	local tmp="$1"

	# Keep the existing inode when the hosts file is bind-mounted (for example /etc/hosts in CI containers).
	if [[ -e "${DNS_HOSTS_FILE}" ]]; then
		dns_write_file_in_place "${tmp}" "${DNS_HOSTS_FILE}"
	else
		dns_run_with_optional_sudo install -m 0644 "${tmp}" "${DNS_HOSTS_FILE}"
	fi
	rm -f "${tmp}"
}

dns_strip_hosts_fallback_block() {
	local tmp

	tmp="$(mktemp)"
	if [[ -f "${DNS_HOSTS_FILE}" ]]; then
		awk -v begin="${DNS_HOSTS_BLOCK_BEGIN}" -v end="${DNS_HOSTS_BLOCK_END}" '
			$0 == begin { skip=1; next }
			$0 == end { skip=0; next }
			!skip { print }
		' "${DNS_HOSTS_FILE}" >"${tmp}"
	fi
	printf '%s\n' "${tmp}"
}

dns_write_hosts_fallback() {
	local tmp stripped

	tmp="$(mktemp)"
	stripped="$(dns_strip_hosts_fallback_block)"

	{
		if [[ -s "${stripped}" ]]; then
			cat "${stripped}"
			printf '\n'
		fi
		printf '%s\n' "${DNS_HOSTS_BLOCK_BEGIN}"
		while IFS= read -r host; do
			printf '127.0.0.1 %s\n' "${host}"
		done < <(dns_read_hosts_fallback_entries)
		printf '%s\n' "${DNS_HOSTS_BLOCK_END}"
	} >"${tmp}"

	dns_rewrite_hosts_file "${tmp}"
	rm -f "${stripped}"
}

dns_remove_hosts_fallback() {
	local stripped

	if [[ ! -f "${DNS_HOSTS_FILE}" ]]; then
		return 0
	fi

	stripped="$(dns_strip_hosts_fallback_block)"
	dns_rewrite_hosts_file "${stripped}"
}

dns_test_resolution() {
	local checked=0 failed=0 host

	echo
	echo ">>> Testing resolution"
	if [[ "${DNS_HOSTS_FILE}" == "/etc/hosts" ]]; then
		while IFS= read -r host; do
			if ! getent hosts "${host}"; then
				echo "    FAIL: ${host}"
				failed=$((failed + 1))
			fi
			checked=$((checked + 1))
			if [[ "${checked}" -ge 3 ]]; then
				break
			fi
		done < <(dns_read_hosts_fallback_entries)
		if [[ "${failed}" -gt 0 ]]; then
			echo ">>> ERROR: ${failed}/${checked} test names do not resolve; local DNS is NOT working." >&2
			return 1
		fi
	else
		echo ">>> Skipping getent check for custom hosts file: ${DNS_HOSTS_FILE}"
	fi
}
