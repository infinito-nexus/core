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
# this script runs.
set -eu

CA_DIR="/opt/registry-cache-ca"
CA_SRC="${CA_DIR}/ca.crt"

# Distro-specific anchor location and bundle-rebuild command. Supported:
#   * Debian/Ubuntu: anchors in /usr/local/share/ca-certificates (must end
#     in .crt); `update-ca-certificates` rebuilds /etc/ssl/certs/ca-certificates.crt.
#   * Arch/Fedora (p11-kit): anchors in /etc/ca-certificates/trust-source/anchors;
#     `update-ca-trust extract` rebuilds the bundle.
# Detect by command availability, since IDs vary across container variants.
if command -v update-ca-certificates >/dev/null 2>&1; then
	CA_DST="/usr/local/share/ca-certificates/infinito-registry-cache.crt"
	CA_REBUILD=(update-ca-certificates)
elif command -v update-ca-trust >/dev/null 2>&1; then
	CA_DST="/etc/ca-certificates/trust-source/anchors/infinito-registry-cache.crt"
	CA_REBUILD=(update-ca-trust extract)
else
	echo "[registry-cache-ca] no supported CA trust tool (update-ca-certificates or update-ca-trust)" >&2
	exit 1
fi

# Bind mount absent → solo-service debugging without the registry-cache.
# dockerd will fall back to direct registry pulls; that is supported.
if [ ! -d "${CA_DIR}" ]; then
	echo "[registry-cache-ca] ${CA_DIR} not mounted; skipping" >&2
	exit 0
fi

# Bind mount present but ca.crt missing → registry-cache hasn't generated
# its CA yet. dockerd MUST NOT boot in this state because compose forces
# HTTP_PROXY through the proxy; without the CA every pull will fail with
# x509 unknown-authority. Refuse to start so the operator notices the
# ordering bug instead of debugging cryptic TLS errors mid-deploy.
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
"${CA_REBUILD[@]}" >/dev/null 2>&1
echo "[registry-cache-ca] installed ${CA_DST}" >&2
