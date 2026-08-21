#!/usr/bin/env bash
# Wait for an onion service to answer over the Tor SOCKS proxy. If it never
# comes up within the first attempt budget, recreate the Tor container once
# (fresh guards/circuits + descriptor republish) and retry the budget again.
#
# Args:
#   $1 socks     -- Tor SOCKS host:port
#   $2 domain    -- onion domain (plaintext http; Tor provides the encryption)
#   $3 attempts  -- probe attempts per pass
#   $4 delay     -- seconds between attempts
#   $5 tor_dir   -- svc-net-tor compose instance dir (for --force-recreate)
set -euo pipefail

socks="${1:?socks host:port required}"
domain="${2:?onion domain required}"
attempts="${3:?attempts required}"
delay="${4:?delay seconds required}"
tor_dir="${5:?tor compose dir required}"

url="http://${domain}/"

probe() {
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl --silent --show-error --location --max-time 120 --socks5-hostname "${socks}" \
        -o /dev/null "${url}"; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

if probe; then
  exit 0
fi

echo ">>> ${domain} did not answer in ${attempts} attempts; recreating Tor for fresh circuits"
if docker service inspect tor_tor >/dev/null 2>&1; then
	docker service update --force tor_tor --detach
else
	(cd "${tor_dir}" && compose up -d --force-recreate --remove-orphans)
fi

probe
