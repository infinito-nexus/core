#!/bin/sh
# Run 32118850138 could bound the dnsmasq listener loss only to a 6m39s
# window between two host DNS consumers; one line per 10s pins it to one
# sample bucket and names which :53 listener (hex local_address) was left.
set -u

sample_once() {
	socks="$(awk '$2 ~ /:0035$/ && $3 == "00000000:0000" {printf " %s", $2}' "${1}")"
	printf '%s%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${socks:- none}"
}

[ "${DNS53_SAMPLER_LIB:-}" = "1" ] && return 0

: "${INFINITO_RESCUE_DIAGNOSTICS_DIR:?INFINITO_RESCUE_DIAGNOSTICS_DIR must be set}"
mkdir -p "${INFINITO_RESCUE_DIAGNOSTICS_DIR}"
while :; do
	sample_once /proc/net/udp >>"${INFINITO_RESCUE_DIAGNOSTICS_DIR}/dns53-sampler.log"
	sleep 10
done
