#!/usr/bin/env bash
# No `set -e`: a poll iteration that finds no token yet must not abort the loop.
set -o pipefail

container service update --force --replicas 1 "${SERVICE_REF}" >/dev/null

deadline=$(($(date +%s) + DEADLINE_S))
while [ "$(date +%s)" -lt "${deadline}" ]; do
	token="$(container service logs --no-task-ids "${SERVICE_REF}" 2>&1 |
		sed -E 's/^[^|]*\| //' |
		grep -oE '^[a-f0-9]{32,64}$' | tail -1)"
	if [ -n "${token}" ]; then
		printf '%s\n' "${token}"
		exit 0
	fi
	sleep "${POLL_DELAY_S}"
done
exit 1
