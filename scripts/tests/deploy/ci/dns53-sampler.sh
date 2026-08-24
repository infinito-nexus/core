#!/bin/sh
# Run 32118850138 could bound the dnsmasq listener loss only to a 6m39s
# window between two host DNS consumers; one line per 10s pins it to one
# sample bucket and names which :53 listener (hex local_address) was left.
set -u

EXTERNAL_PROBE_NAME=deb.debian.org

sample_once() {
	socks="$(awk '$2 ~ /:0035$/ && $3 == "00000000:0000" {printf " %s", $2}' "${1}")"
	printf '%s%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${socks:- none}"
}

zone_probe_name() {
	zone="$(sed -n 's|^[[:space:]]*address=/\([^/]*\)/.*|\1|p' "${1}" 2>/dev/null | head -n1)"
	[ -n "${zone}" ] || return 0
	printf 'rescue-probe.%s' "${zone}"
}

answer_once() {
	name="${1}"
	start="$(date -u '+%s%3N')"
	if timeout 3 getent ahosts "${name}" >/dev/null 2>&1; then
		verdict=ok
	else
		verdict=fail
	fi
	printf ' %s=%s/%sms' "${name}" "${verdict}" "$(($(date -u '+%s%3N') - start))"
}

[ "${DNS53_SAMPLER_LIB:-}" = "1" ] && return 0

: "${INFINITO_DNS53_SAMPLER_LOG:?INFINITO_DNS53_SAMPLER_LOG must be set}"
mkdir -p "$(dirname "${INFINITO_DNS53_SAMPLER_LOG}")"
while :; do
	{
		printf '%s' "$(sample_once /proc/net/udp)"
		inzone="$(zone_probe_name /etc/dnsmasq.conf)"
		if [ -n "${inzone}" ]; then
			answer_once "${inzone}"
		else
			printf ' inzone=unconfigured'
		fi
		answer_once "${EXTERNAL_PROBE_NAME}"
		printf '\n'
	} >>"${INFINITO_DNS53_SAMPLER_LOG}"
	sleep 10
done
