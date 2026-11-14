#!/usr/bin/env bash
# Args:
#   $1 tor_dir       -- svc-net-tor compose instance dir (for --force-recreate)
#   $2 tor_lock      -- empty in the serial run, which recreates at once; in the
#                       parallel run the lock file whose exclusive lock the
#                       recreate holds, announced by <tor_lock>.recreate-pending
#   $3 wait_seconds  -- seconds to wait for the exclusive lock
# Exit:
#   0 after the recreate, <tor_lock>.recreate-pending left for the caller to
#   remove once its probe ended; 75 when onion runs held the lock for
#   wait_seconds and the recreate was skipped; any other code when it failed
set -euo pipefail

tor_dir="${1:?tor compose dir required}"
tor_lock="${2?tor lock file or empty required}"
wait_seconds="${3:?wait seconds required}"

if [ -n "${tor_lock}" ]; then
	pending="${tor_lock}.recreate-pending"
	echo ">>> waiting up to ${wait_seconds}s until no onion run uses Tor"
	touch "${pending}"
	exec 9>>"${tor_lock}"
	if ! flock -x -w "${wait_seconds}" 9; then
		rm -f "${pending}"
		echo ">>> skipped recreating Tor: onion Playwright runs held ${tor_lock} for ${wait_seconds}s" >&2
		exit 75
	fi
fi

echo ">>> recreating Tor for fresh circuits"
if docker service inspect tor_tor >/dev/null 2>&1; then
	docker service update --force tor_tor
else
	(cd "${tor_dir}" && compose up -d --force-recreate --remove-orphans)
fi
