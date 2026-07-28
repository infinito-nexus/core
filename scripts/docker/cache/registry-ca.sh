#!/usr/bin/env bash
# Install the registry-cache MITM CA certificate into the runner
# container's system trust store before dockerd starts.
#
# The `registry-cache` service in compose.yml runs
# rpardini/docker-registry-proxy and performs SSL bumping on every
# outbound docker registry pull. Inner dockerd MUST trust the proxy's
# self-signed CA, otherwise every HTTPS pull fails with x509 errors.
#
# Idempotent: safe to run on every dockerd restart. The bind-mount-absent
# case is reserved for solo-service debugging (no `ci` profile, registry-
# cache not present); in normal operation compose.yml gates `infinito` on
# `registry-cache` being healthy, so the CA is always on disk by the time
# this script runs. A mounted dir with no ca.crt is refused instead of
# skipped: compose forces HTTP_PROXY through the proxy, so booting without
# the CA turns an ordering bug into cryptic x509 failures mid-deploy.
#
# Anchor dir and rebuild command are detected by capability, not distro id:
#   * Debian/Ubuntu: /usr/local/share/ca-certificates (name must end in .crt),
#     rebuilt by `update-ca-certificates`.
#   * Arch and Fedora/CentOS both rebuild with `update-ca-trust extract` but
#     read different anchor dirs -- Arch has no /etc/pki, the RedHat family
#     has no /etc/ca-certificates -- so the dir is probed, not assumed.
set -eu

CA_DIR="/opt/registry-cache-ca"
CA_SRC="${CA_DIR}/ca.crt"

if command -v update-ca-certificates >/dev/null 2>&1; then
	CA_DST="/usr/local/share/ca-certificates/infinito-registry-cache.crt"
	CA_REBUILD=(update-ca-certificates)
elif command -v update-ca-trust >/dev/null 2>&1; then
	if [ -d /etc/pki/ca-trust/source/anchors ]; then
		CA_DST="/etc/pki/ca-trust/source/anchors/infinito-registry-cache.crt"
	elif [ -d /etc/ca-certificates/trust-source/anchors ]; then
		CA_DST="/etc/ca-certificates/trust-source/anchors/infinito-registry-cache.crt"
	else
		echo "[registry-cache-ca] update-ca-trust present but no known anchor dir (/etc/pki/ca-trust/source/anchors, /etc/ca-certificates/trust-source/anchors)" >&2
		exit 1
	fi
	CA_REBUILD=(update-ca-trust extract)
else
	echo "[registry-cache-ca] no supported CA trust tool (update-ca-certificates or update-ca-trust)" >&2
	exit 1
fi

if [ ! -d "${CA_DIR}" ]; then
	echo "[registry-cache-ca] ${CA_DIR} not mounted; skipping" >&2
	exit 0
fi

if [ ! -s "${CA_SRC}" ]; then
	echo "[registry-cache-ca] CA missing at ${CA_SRC} but ${CA_DIR} is mounted." >&2
	echo "[registry-cache-ca] registry-cache must be healthy before dockerd starts;" >&2
	echo "[registry-cache-ca] check compose.yml depends_on (condition: service_healthy)." >&2
	exit 1
fi

if cmp -s "${CA_SRC}" "${CA_DST}" 2>/dev/null; then
	exit 0
fi

install -d -m 0755 "$(dirname "${CA_DST}")"
install -m 0644 "${CA_SRC}" "${CA_DST}"
"${CA_REBUILD[@]}" >/dev/null
echo "[registry-cache-ca] installed ${CA_DST}" >&2
