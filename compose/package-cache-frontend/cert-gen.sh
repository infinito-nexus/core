#!/bin/sh
# In-container CA + per-hostname cert generator.
# See docs/contributing/environment/cache.md.

set -eu

CA_CRT=/ca/ca.crt
CA_KEY=/ca/ca.key

CA_DAYS=3650
LEAF_DAYS=730

HOSTNAMES="pypi.org files.pythonhosted.org registry.npmjs.org rubygems.org index.rubygems.org repo.packagist.org proxy.golang.org dl-cdn.alpinelinux.org raw.githubusercontent.com codeload.github.com"

log() { printf '[package-frontend-certs] %s\n' "$*" >&2; }

ensure_openssl() {
	if command -v openssl >/dev/null 2>&1; then
		return 0
	fi
	log "openssl not present in image — installing via apk"
	apk add --no-cache openssl >/dev/null 2>&1
}

mkdir -p /ca /certs
chmod 0700 /ca

ensure_openssl

cert_still_valid() {
	crt="$1"
	[ -s "${crt}" ] || return 1
	openssl x509 -in "${crt}" -noout -checkend 2592000 >/dev/null 2>&1
}

ensure_ca() {
	if cert_still_valid "${CA_CRT}" && [ -s "${CA_KEY}" ]; then
		log "CA already valid: ${CA_CRT}"
		return 0
	fi
	log "Generating new root CA at ${CA_CRT}"
	openssl genrsa -out "${CA_KEY}" 4096 >/dev/null 2>&1
	chmod 0600 "${CA_KEY}"
	openssl req -x509 -new -nodes \
		-key "${CA_KEY}" \
		-sha256 \
		-days "${CA_DAYS}" \
		-subj "/CN=Infinito Package-Cache Frontend CA/O=Infinito.Nexus" \
		-addext "basicConstraints=critical,CA:TRUE" \
		-addext "keyUsage=critical,keyCertSign,cRLSign" \
		-addext "subjectKeyIdentifier=hash" \
		-out "${CA_CRT}" >/dev/null 2>&1
	chmod 0644 "${CA_CRT}"
}

ensure_leaf() {
	hostname="$1"
	crt="/certs/${hostname}.crt"
	key="/certs/${hostname}.key"

	if cert_still_valid "${crt}" && [ -s "${key}" ]; then
		# Reject leaf if it no longer chains to the current CA.
		if openssl verify -CAfile "${CA_CRT}" "${crt}" >/dev/null 2>&1; then
			return 0
		fi
		log "Leaf for ${hostname} no longer chains to current CA; regenerating"
	fi

	log "Generating leaf cert for ${hostname}"
	openssl genrsa -out "${key}" 2048 >/dev/null 2>&1
	chmod 0600 "${key}"

	# Modern TLS clients require SAN; CN-as-host is no longer honoured.
	extfile="$(mktemp)"
	{
		printf 'subjectAltName = DNS:%s\n' "${hostname}"
		printf 'extendedKeyUsage = serverAuth\n'
	} >"${extfile}"

	csr="$(mktemp)"
	openssl req -new \
		-key "${key}" \
		-subj "/CN=${hostname}" \
		-out "${csr}" >/dev/null 2>&1

	openssl x509 -req \
		-in "${csr}" \
		-CA "${CA_CRT}" \
		-CAkey "${CA_KEY}" \
		-CAcreateserial \
		-out "${crt}" \
		-days "${LEAF_DAYS}" \
		-sha256 \
		-extfile "${extfile}" >/dev/null 2>&1
	chmod 0644 "${crt}"

	rm -f "${csr}" "${extfile}"
}

ensure_ca
count=0
for h in ${HOSTNAMES}; do
	ensure_leaf "${h}"
	count=$((count + 1))
done
log "CA + ${count} leaf certs ready under /certs"
