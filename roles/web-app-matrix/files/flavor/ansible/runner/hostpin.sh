#!/bin/bash
set -euo pipefail

if [ -z "${MATRIX_OIDC_ONION_HOST:-}" ]; then
  echo ">>> matrix-mdad-hostpin: MATRIX_OIDC_ONION_HOST unset, nothing to pin"
  exit 0
fi

_gw_hex="$(awk '$2 == "00000000" { print $3; exit }' /proc/net/route)"
if [ -z "${_gw_hex}" ]; then
  echo "!!! matrix-mdad-hostpin: no default route found, skipping pin" >&2
  exit 0
fi
_gw="$(printf '%d.%d.%d.%d' "0x${_gw_hex:6:2}" "0x${_gw_hex:4:2}" "0x${_gw_hex:2:2}" "0x${_gw_hex:0:2}")"

_hosts_tmp="$(mktemp)"
grep -v "[[:space:]]${MATRIX_OIDC_ONION_HOST}\$" /etc/hosts > "${_hosts_tmp}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
printf '%s\t%s\n' "${_gw}" "${MATRIX_OIDC_ONION_HOST}" >> "${_hosts_tmp}"
cat "${_hosts_tmp}" > /etc/hosts
rm -f "${_hosts_tmp}"
echo ">>> matrix-mdad-hostpin: pinned ${MATRIX_OIDC_ONION_HOST} -> ${_gw} (node OpenResty)"
