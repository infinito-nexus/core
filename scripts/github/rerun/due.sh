#!/usr/bin/env bash
#
# Emit due=true on GITHUB_OUTPUT when the current hour opens an interval window
# counted from 00:00 UTC. Intervals are rounded up to whole hours.
#
# Inputs via env:
#   INTERVAL_MINUTES  wanted interval between two sweeps

set -euo pipefail

: "${INTERVAL_MINUTES:?Missing INTERVAL_MINUTES}"
: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

hours="$(((INTERVAL_MINUTES + 59) / 60))"

if ((hours < 1)); then
	hours=1
fi

hour="$((10#$(date -u +%H)))"

if ((hour % hours == 0)); then
	echo "$(date -u +%H:%M) UTC opens the ${hours}h window, sweeping"
	echo "due=true" >>"${GITHUB_OUTPUT}"
else
	echo "$(date -u +%H:%M) UTC is inside the ${hours}h window, skipping"
	echo "due=false" >>"${GITHUB_OUTPUT}"
fi
