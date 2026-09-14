#!/bin/bash
# Gate the container on Tor being able to carry traffic.
#
# Param: $1 - Tor DataDirectory, the directory holding control_auth_cookie
set -u

data_dir=${1:?usage: tor-healthcheck.sh <DataDirectory>}
cookie="${data_dir}/control_auth_cookie"

[ -r "${cookie}" ] || exit 1
hex=$(od -An -v -tx1 <"${cookie}" | tr -d ' \n')
[ -n "${hex}" ] || exit 1

exec 3<>/dev/tcp/127.0.0.1/9051 || exit 1
printf 'AUTHENTICATE %s\r\nGETINFO status/circuit-established\r\nQUIT\r\n' "${hex}" >&3
grep -q 'circuit-established=1' <&3
