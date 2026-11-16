#!/usr/bin/env bash
set -euo pipefail

sources="/etc/apt/sources.list.d/ubuntu.sources"
if [[ ! -f "${sources}" ]]; then
	exit 0
fi

: "${INFINITO_APT_UBUNTU_MIRRORS:?INFINITO_APT_UBUNTU_MIRRORS must be set}"
: "${INFINITO_APT_UBUNTU_PORTS_MIRRORS:?INFINITO_APT_UBUNTU_PORTS_MIRRORS must be set}"
read -r -a mirrors <<<"${INFINITO_APT_UBUNTU_MIRRORS}"
read -r -a ports_mirrors <<<"${INFINITO_APT_UBUNTU_PORTS_MIRRORS}"

mirrorlist="/etc/apt/ubuntu.mirrorlist"
ports_mirrorlist="/etc/apt/ubuntu-ports.mirrorlist"
printf '%s\n' "${mirrors[@]}" | awk '{ printf "%s\tpriority:%d\n", $0, NR }' >"${mirrorlist}"
printf '%s\n' "${ports_mirrors[@]}" | awk '{ printf "%s\tpriority:%d\n", $0, NR }' >"${ports_mirrorlist}"
printf 'Acquire::http::Timeout "10";\n' >/etc/apt/apt.conf.d/80infinito-mirrors
sed -i -E \
	-e "s#^URIs: http://(archive|security)\.ubuntu\.com/ubuntu/?\$#URIs: mirror+file:${mirrorlist}#" \
	-e "s#^URIs: http://ports\.ubuntu\.com/ubuntu-ports/?\$#URIs: mirror+file:${ports_mirrorlist}#" \
	"${sources}"
