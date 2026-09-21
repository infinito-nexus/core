#!/usr/bin/env bash

DNS_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DNS_PROJECT_ROOT="$(cd "${DNS_SCRIPT_DIR}/../../../.." && pwd)"
DNS_DOMAIN="${INFINITO_DNS_DOMAIN}"
DNS_HOSTS_FILE="${INFINITO_DNS_HOSTS_FILE}"
DNS_HOSTS_BLOCK_BEGIN="# BEGIN infinito-dns-fallback"
DNS_HOSTS_BLOCK_END="# END infinito-dns-fallback"
DNS_HOSTS_GENERATOR="${DNS_PROJECT_ROOT}/cli/meta/domains/__main__.py"

# shellcheck disable=SC2034
DNS_NM_CONF="/etc/NetworkManager/conf.d/00-infinito-dnsmasq.conf"
DNS_NM_DNSMASQ_DIR="/etc/NetworkManager/dnsmasq.d"
# shellcheck disable=SC2034
DNS_NM_DNSMASQ_CONF="${DNS_NM_DNSMASQ_DIR}/${DNS_DOMAIN}.conf"
# shellcheck disable=SC2034
DNS_SYS_DNSMASQ_CONF="/etc/dnsmasq.d/${DNS_DOMAIN}.conf"

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
	local domain="$1" output

	if ! command -v python3 >/dev/null 2>&1 || [[ ! -f "${DNS_HOSTS_GENERATOR}" ]]; then
		return 1
	fi

	if ! output="$(
		DOMAIN="${domain}" PYTHONPATH="${DNS_PROJECT_ROOT}" python3 -m cli.meta.domains --domain-primary "${domain}" --alias --www
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

dns_env_value() {
	awk -v key="$2" 'index($0, key "=") == 1 { value = substr($0, length(key) + 2) } END { gsub(/"/, "", value); print value }' "$1"
}

dns_checkout_stacks() {
	local listing path domain ip

	if ! listing="$(git -C "${DNS_PROJECT_ROOT}" worktree list --porcelain 2>/dev/null)"; then
		listing="worktree ${DNS_PROJECT_ROOT}"
	fi

	while IFS= read -r path; do
		if [[ ! -f "${path}/.env" ]]; then
			continue
		fi
		domain="$(dns_env_value "${path}/.env" INFINITO_DOMAIN)"
		ip="$(dns_env_value "${path}/.env" INFINITO_BIND_IP)"
		if [[ "${domain}" == *".${DNS_DOMAIN}" && -n "${ip}" ]]; then
			printf '%s %s %s\n' "${domain}" "${ip}" "${path}"
		fi
	done < <(printf '%s\n' "${listing}" | awk 'index($0, "worktree ") == 1 { print substr($0, 10) }')
}

# Param: none. Output: one "<INFINITO_DOMAIN> <INFINITO_BIND_IP>" line per checkout whose .env places its stack below INFINITO_DNS_DOMAIN; exits 2 when two checkouts claim one domain.
dns_stacks() {
	dns_checkout_stacks | awk '
		$1 in ip && ip[$1] != $2 {
			printf "ERROR: %s is claimed by %s and %s\n", $1, path[$1], $3 > "/dev/stderr"
			exit 2
		}
		!($1 in ip) { ip[$1] = $2; path[$1] = $3; print $1, $2 }
	'
}

dns_stack_dnsmasq_lines() {
	dns_stacks | awk '{ printf "address=/%s/%s\nlocal=/%s/\n", $1, $2, $1 }'
}

dns_dnsmasq_config() {
	cat <<EOF
address=/${DNS_DOMAIN}/127.0.0.1
address=/${DNS_DOMAIN}/::1
EOF
	dns_stack_dnsmasq_lines
}

dns_hosts_fallback_lines() {
	local domain ip

	if [[ -n "${INFINITO_DNS_HOSTS:-}" ]]; then                                               # nocheck: infinito-dns-hosts-optional
		dns_read_hosts_fallback_entries_from_raw "${INFINITO_DNS_HOSTS}" | sed 's/^/127.0.0.1 /' # nocheck: infinito-dns-hosts-optional
		return
	fi

	dns_stacks | while read -r domain ip; do
		{
			dns_read_generated_hosts_fallback_entries "${domain}" ||
				dns_read_hosts_fallback_entries_from_raw "${domain} dashboard.${domain} matomo.${domain}"
		} | sed "s/^/${ip} /"
	done
}

dns_read_hosts_fallback_entries() {
	dns_hosts_fallback_lines | awk '{ print $2 }'
}

dns_rewrite_hosts_file() {
	local tmp="$1"

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
		dns_hosts_fallback_lines
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
	local checked=0 host

	echo
	echo ">>> Testing resolution"
	if [[ "${DNS_HOSTS_FILE}" == "/etc/hosts" ]]; then
		while IFS= read -r host; do
			getent hosts "${host}" || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
			checked=$((checked + 1))
			if [[ "${checked}" -ge 3 ]]; then
				break
			fi
		done < <(dns_read_hosts_fallback_entries)
	else
		echo ">>> Skipping getent check for custom hosts file: ${DNS_HOSTS_FILE}"
	fi
}
