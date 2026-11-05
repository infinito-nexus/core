#!/usr/bin/env bash
# Wait for an onion service to answer over the Tor SOCKS proxy. If it never
# comes up within the first attempt budget, recreate the Tor container once
# (fresh guards/circuits + descriptor republish) and retry the budget again.
# Any status below 500 counts and redirects are not followed: an SSO-gated
# vhost redirects to the clearnet issuer, which Tor cannot reach.
#
# Args:
#   $1 socks     -- Tor SOCKS host:port
#   $2 domain    -- onion domain (plaintext http; Tor provides the encryption)
#   $3 attempts  -- probe attempts per pass
#   $4 delay     -- seconds between attempts
#   $5 max_time  -- seconds one probe attempt may take
#   $6 tor_dir   -- svc-net-tor compose instance dir (for --force-recreate)
#   $7 tor_lock  -- empty in the serial run, which recreates at once; in the
#                   parallel run the lock file whose exclusive lock the
#                   recreate holds. The scheduler holds a shared lock per
#                   running onion run and starts no new one while
#                   <tor_lock>.recreate-pending exists. When onion runs still
#                   hold it after attempts x delay, the recreate is skipped
#                   and the current circuits get one more probe pass.
set -euo pipefail

socks="${1:?socks host:port required}"
domain="${2:?onion domain required}"
attempts="${3:?attempts required}"
delay="${4:?delay seconds required}"
max_time="${5:?max time per attempt required}"
tor_dir="${6:?tor compose dir required}"
tor_lock="${7?tor lock file or empty required}"

url="http://${domain}/"

probe() {
  local i code
  for ((i = 1; i <= attempts; i++)); do
    if code="$(curl --silent --show-error --max-time "${max_time}" --socks5-hostname "${socks}" \
        -o /dev/null -w '%{http_code}' "${url}")" && [ "${code}" -lt 500 ]; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

if probe; then
  exit 0
fi

if [ -n "${tor_lock}" ]; then
	pending="${tor_lock}.recreate-pending"
	wait_seconds=$((attempts * delay))
	echo ">>> ${domain} did not answer in ${attempts} attempts; waiting up to ${wait_seconds}s until no onion run uses Tor"
	touch "${pending}"
	trap 'rm -f "${pending}"' EXIT
	exec 9>>"${tor_lock}"
	if ! flock -x -w "${wait_seconds}" 9; then
		rm -f "${pending}"
		echo ">>> skipped recreating Tor for ${domain}: onion Playwright runs held ${tor_lock} for ${wait_seconds}s; probing the current circuits once more" >&2
		probe
		exit 0
	fi
fi

echo ">>> ${domain} did not answer in ${attempts} attempts; recreating Tor for fresh circuits"
if docker service inspect tor_tor >/dev/null 2>&1; then
	docker service update --force tor_tor --detach
else
	(cd "${tor_dir}" && compose up -d --force-recreate --remove-orphans)
fi

probe
