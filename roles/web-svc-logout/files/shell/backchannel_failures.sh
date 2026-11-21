#!/usr/bin/env bash
set -euo pipefail

: "${SINCE:?SINCE env var is required}"
: "${SERVICE:?SERVICE env var is required}"
: "${SWARM:?SWARM env var is required}"

if [ "${SWARM}" = "true" ]; then
	log=(container service logs --no-task-ids --since "${SINCE}" "${SERVICE}")
else
	log=(container logs --since "${SINCE}" "${SERVICE}")
fi

timeout 60 "${log[@]}" |
	sed -nE \
		-e "s/.*Received response for backchannel-logout from client\. clientId='([^']+)'.* status=([0-9]+) success=false.*/\1 \2/p" \
		-e "s/.*KC-SERVICES0057: Logout for client '([^']+)' failed.*/\1 unreachable/p" |
	sort -u
