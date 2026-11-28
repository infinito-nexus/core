#!/bin/sh
# Param PROXMOX_API_SAN: the subjectAltName of the name the API consumers dial, DNS:<name> or IP:<address>.
# Param PROXMOX_API_CERT_DAYS: the lifetime of a new certificate in days.
# Param PROXMOX_API_CERT_RENEW_SECONDS: a certificate that expires within this many seconds is replaced.
# Param PROXMOX_API_RSA_BITS: the RSA key size of a new certificate.
set -eu

: "${PROXMOX_API_SAN:?}" "${PROXMOX_API_CERT_DAYS:?}" "${PROXMOX_API_CERT_RENEW_SECONDS:?}" "${PROXMOX_API_RSA_BITS:?}"

PROXMOX_API_CERT=/etc/pve/local/pveproxy-ssl.pem

served_names() {
	openssl x509 -in "$PROXMOX_API_CERT" -noout -ext subjectAltName |
		tail -n +2 | sed 's/IP Address:/IP:/g' | tr -d ' ' | tr ',' '\n'
}

current() {
	[ -s "$PROXMOX_API_CERT" ] || return 1
	openssl x509 -in "$PROXMOX_API_CERT" -noout -checkend "$PROXMOX_API_CERT_RENEW_SECONDS" >/dev/null || return 1
	served_names | grep -qxF "$PROXMOX_API_SAN"
}

if current; then
	echo "[OK] pveproxy serves a certificate for $PROXMOX_API_SAN" >&2
else
	work=$(mktemp -d)
	trap 'rm -rf "$work"' EXIT
	openssl req -x509 -newkey "rsa:$PROXMOX_API_RSA_BITS" -nodes \
		-keyout "$work/key.pem" -out "$work/cert.pem" \
		-days "$PROXMOX_API_CERT_DAYS" -subj "/CN=${PROXMOX_API_SAN#*:}" \
		-addext "subjectAltName=$PROXMOX_API_SAN" \
		-addext "basicConstraints=critical,CA:FALSE" \
		-addext "keyUsage=critical,digitalSignature,keyEncipherment" \
		-addext "extendedKeyUsage=serverAuth" 2>/dev/null
	pvenode cert set "$work/cert.pem" "$work/key.pem" --force 1 --restart 1 >/dev/null
	current || {
		echo "[FAIL] pveproxy does not serve the new certificate for $PROXMOX_API_SAN" >&2
		exit 1
	}
	echo "[CHANGED] pveproxy serves a new certificate for $PROXMOX_API_SAN" >&2
fi

printf 'fingerprint=%s\n' "$(openssl x509 -in "$PROXMOX_API_CERT" -noout -fingerprint -sha256 | sed 's/^[^=]*=//; s/://g' | tr 'A-F' 'a-f')"
openssl x509 -in "$PROXMOX_API_CERT"
