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
#     read different anchor dirs, and with-ca-trust.sh creates both dirs on
#     both families, so the anchor goes into each.
# Param: CA_ROOT  prefix for every absolute path below; empty in production.
set -eu

CA_ROOT="${CA_ROOT:-}"
CA_DIR="${CA_ROOT}/opt/registry-cache-ca"
CA_SRC="${CA_DIR}/ca.crt"
CA_NAME="infinito-registry-cache.crt"

if command -v update-ca-certificates >/dev/null 2>&1; then
	CA_DSTS=("${CA_ROOT}/usr/local/share/ca-certificates/${CA_NAME}")
	CA_REBUILD=(update-ca-certificates)
elif command -v update-ca-trust >/dev/null 2>&1; then
	CA_DSTS=(
		"${CA_ROOT}/etc/pki/ca-trust/source/anchors/${CA_NAME}"
		"${CA_ROOT}/etc/ca-certificates/trust-source/anchors/${CA_NAME}"
	)
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

changed=0
for dst in "${CA_DSTS[@]}"; do
	if ! cmp -s "${CA_SRC}" "${dst}" 2>/dev/null; then
		install -d -m 0755 "$(dirname "${dst}")"
		install -m 0644 "${CA_SRC}" "${dst}"
		changed=1
	fi
done

if [ "${changed}" -eq 0 ]; then
	exit 0
fi

"${CA_REBUILD[@]}" >/dev/null
echo "[registry-cache-ca] installed ${CA_DSTS[*]}" >&2
