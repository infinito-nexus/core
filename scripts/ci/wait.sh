#!/usr/bin/env bash
set -euo pipefail

# Wait for an external CI state to become available, polling at a fixed interval
# until a timeout, so a routine never needs its own shell loop (requirement
# 041). Exits 0 when the state is available, non-zero at the timeout.
# Inputs (env):
#   kind     - job-log | run | check: what to wait for
#   id       - the job, run or check id
#   interval - seconds between polls
#   timeout  - seconds before giving up

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${_repo_root}"

kind="${kind:-}"
id="${id:-}"
interval="${interval:-}"
timeout="${timeout:-}"

for _required in kind id interval timeout; do
	if [ -z "${!_required}" ]; then
		echo "ci-wait: ${_required}= is required (kind=job-log|run|check id= interval=<s> timeout=<s>)." >&2
		exit 2
	fi
done

available() {
	case "${kind}" in
	run)
		[ "$(gh run view "${id}" --json status --jq .status 2>/dev/null)" = completed ]
		;;
	check)
		[ "$(gh api "repos/{owner}/{repo}/check-runs/${id}" --jq .status 2>/dev/null)" = completed ]
		;;
	job-log)
		gh api "repos/{owner}/{repo}/actions/jobs/${id}/logs" --allow-escape-sequences >/dev/null 2>&1
		;;
	*)
		echo "ci-wait: kind must be job-log, run or check, got '${kind}'." >&2
		exit 2
		;;
	esac
}

_deadline=$(($(date +%s) + timeout))
while true; do
	if available; then
		exit 0
	fi
	if [ "$(date +%s)" -ge "${_deadline}" ]; then
		echo "ci-wait: timed out after ${timeout}s waiting for ${kind} ${id}." >&2
		exit 1
	fi
	sleep "${interval}"
done
