#!/usr/bin/env bash
# shellcheck shell=bash
#
# End-to-end onion smoke test for the svc-net-tor node.
#
# Reaches a deployed svc-net-tor onion service over the Tor network via the
# node's local SOCKS proxy and asserts the target subdomain responds. Retries
# against transient Tor-network / hidden-service-publication delays.
#
# Usage:
#   <this script> <onion-host> [socks-host:port] [retries] [sleep-seconds]
#
# Example:
#   <this script> dashboard.abc...xyz.onion 127.0.0.1:<socks-port> 20 15

set -euo pipefail

ONION_HOST="${1:?onion host required, e.g. dashboard.<node>.onion}"
SOCKS="${2:?socks host:port required, pass 127.0.0.1:<svc-net-tor services.tor.ports.local.socks>}"
RETRIES="${3:-20}"
SLEEP_SECONDS="${4:-15}"

if [[ "${ONION_HOST}" != *.onion ]]; then
	echo "[FATAL] '${ONION_HOST}' is not a .onion host" >&2
	exit 2
fi

echo "[INFO] onion smoke: http://${ONION_HOST} via socks5://${SOCKS} (${RETRIES} tries, ${SLEEP_SECONDS}s apart)"

attempt=1
while [[ "${attempt}" -le "${RETRIES}" ]]; do
	if curl --fail --silent --show-error --location \
		--socks5-hostname "${SOCKS}" \
		--max-time 30 \
		-o /dev/null -w '%{http_code}' \
		"http://${ONION_HOST}/" >/tmp/onion_smoke_code 2>/tmp/onion_smoke_err; then
		code="$(cat /tmp/onion_smoke_code)"
		echo "[OK] ${ONION_HOST} responded (HTTP ${code}) on attempt ${attempt}"
		exit 0
	fi
	echo "[WAIT] attempt ${attempt}/${RETRIES} failed ($(tail -1 /tmp/onion_smoke_err 2>/dev/null)); retrying in ${SLEEP_SECONDS}s ..."
	attempt=$((attempt + 1))
	sleep "${SLEEP_SECONDS}"
done

echo "[FATAL] ${ONION_HOST} did not respond over Tor after ${RETRIES} attempts" >&2
exit 1
