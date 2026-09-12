#!/usr/bin/env bash
set -euo pipefail

sources="/etc/apt/sources.list.d/ubuntu.sources"
if [[ ! -f "${sources}" ]]; then
	exit 0
fi

: "${INFINITO_APT_UBUNTU_MIRRORS:?INFINITO_APT_UBUNTU_MIRRORS must be set}"
read -r -a mirrors <<<"${INFINITO_APT_UBUNTU_MIRRORS}"

mirrorlist="/etc/apt/ubuntu.mirrorlist"
printf '%s\n' "${mirrors[@]}" | awk '{ printf "%s\tpriority:%d\n", $0, NR }' >"${mirrorlist}"
printf 'Acquire::http::Timeout "10";\n' >/etc/apt/apt.conf.d/80infinito-mirrors
sed -i -E "s#^URIs: http://(archive|security)\.ubuntu\.com/ubuntu/?\$#URIs: mirror+file:${mirrorlist}#" "${sources}"
