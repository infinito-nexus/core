#!/usr/bin/env bash
# shellcheck shell=bash
#
# svc-net-tor role test: probe every currently-served domain and assert it
# responds. Onion (.onion) domains are reached through the node's Tor SOCKS
# proxy; any clearnet domains are reached directly. A domain "responds" when the
# reverse proxy returns an HTTP status in 200-499 (5xx or no answer = failure).
#
# Domains are auto-discovered from the deployed OpenResty vhosts
# (<servers>/{http,https}/<domain>.conf); pass explicit domains as arguments to
# override.
#
# Env (all required; the role's test.env carries them):
#   TOR_SOCKS         SOCKS proxy for .onion (127.0.0.1:<svc-net-tor
#                     services.tor.ports.local.socks>)
#   NGINX_SERVERS_DIR the deployed OpenResty servers dir from the nginx lookup
#   RETRIES           attempts per domain
#   SLEEP_SECONDS     wait between attempts
#   TOR_DNSMASQ_CONF  the dnsmasq drop-in path; its directory is scanned for
#                     upstreams when a probe fails

set -uo pipefail

TOR_SOCKS="${TOR_SOCKS:?pass TOR_SOCKS as env (127.0.0.1:<svc-net-tor services.tor.ports.local.socks>)}"
NGINX_SERVERS_DIR="${NGINX_SERVERS_DIR:?pass NGINX_SERVERS_DIR as env (the deployed OpenResty vhost servers dir from the nginx lookup, e.g. /etc/nginx/conf.d/servers)}"
RETRIES="${RETRIES:?pass RETRIES as env (attempts per domain, from svc-net-tor test.env)}"
SLEEP_SECONDS="${SLEEP_SECONDS:?pass SLEEP_SECONDS as env (wait between attempts, from svc-net-tor test.env)}"
TOR_DNSMASQ_CONF="${TOR_DNSMASQ_CONF:?pass TOR_DNSMASQ_CONF as env (the dnsmasq drop-in path, from svc-net-tor vars)}"

discover_domains() {
	find "${NGINX_SERVERS_DIR}/http" "${NGINX_SERVERS_DIR}/https" \
		-maxdepth 1 -type f -name '*.conf' 2>/dev/null |
		sed -E 's#.*/##; s#\.conf$##' | sort -u
}

if [[ "$#" -gt 0 ]]; then
	domains=("$@")
else
	mapfile -t domains < <(discover_domains)
fi

if [[ "${#domains[@]}" -eq 0 ]]; then
	echo "[FATAL] no domains found under ${NGINX_SERVERS_DIR} and none given as arguments" >&2
	exit 2
fi

echo "[INFO] probing ${#domains[@]} domain(s); onion via socks5://${TOR_SOCKS}"

# Probe one domain with retries. Echoes the final HTTP code; returns 0 on success.
probe() {
	local domain="$1" scheme curl_proxy=() attempt=1 code
	if [[ "${domain}" == *.onion ]]; then
		scheme="http"
		curl_proxy=(--socks5-hostname "${TOR_SOCKS}")
	else
		scheme="https"
	fi
	while [[ "${attempt}" -le "${RETRIES}" ]]; do
		code="$(curl "${curl_proxy[@]}" --silent --show-error --location \
			--insecure --max-time 60 \
			-o /dev/null -w '%{http_code}' \
			"${scheme}://${domain}/")"
		if [[ "${code}" =~ ^[234][0-9][0-9]$ ]]; then
			echo "${code}"
			return 0
		fi
		attempt=$((attempt + 1))
		[[ "${attempt}" -le "${RETRIES}" ]] && sleep "${SLEEP_SECONDS}"
	done
	echo "${code:-000}"
	return 1
}

diagnose() {
	local domain="$1" upstream upstreams=()
	echo "       resolv: $(grep -v '^#' /etc/resolv.conf 2>/dev/null | tr '\n' ' ')"
	grep -F "${domain}" /etc/hosts 2>/dev/null | sed 's/^/       hosts: /'
	if ! command -v dig >/dev/null 2>&1; then
		echo "       dig: not installed"
		return
	fi
	echo "       dig: $(dig +short +time=2 +tries=1 "${domain}" A 2>&1 | tr '\n' ' ')"
	mapfile -t upstreams < <(sed -nE 's/^server=([0-9.]+)$/\1/p' "$(dirname "${TOR_DNSMASQ_CONF}")"/*.conf 2>/dev/null)
	for upstream in "${upstreams[@]}"; do
		echo "       dig@${upstream}: $(dig +short +time=2 +tries=1 "@${upstream}" "${domain}" A 2>&1 | tr '\n' ' ')"
	done
}

failed=0
for domain in "${domains[@]}"; do
	if code="$(probe "${domain}")"; then
		printf '[OK]   %-60s HTTP %s\n' "${domain}" "${code}"
	else
		addr="$(getent hosts "${domain}" 2>/dev/null | head -n1)"
		printf '[FAIL] %-60s HTTP %s dns=%s\n' "${domain}" "${code}" "${addr%% *}"
		diagnose "${domain}"
		failed=$((failed + 1))
	fi
done

echo "[INFO] ${#domains[@]} probed, ${failed} failed"
[[ "${failed}" -eq 0 ]]
