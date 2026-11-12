#!/usr/bin/env bash
# Args:
#   $1 socks     -- Tor SOCKS host:port
#   $2 domain    -- onion domain, probed over plaintext http
#   $3 max_time  -- seconds the probe may take
# Exit:
#   0 when the onion answered with a status below 500, non-zero otherwise
set -euo pipefail

socks="${1:?socks host:port required}"
domain="${2:?onion domain required}"
max_time="${3:?max time required}"

code="$(curl --silent --show-error --max-time "${max_time}" --socks5-hostname "${socks}" \
  -o /dev/null -w '%{http_code}' "http://${domain}/")"
[ "${code}" -lt 500 ]
