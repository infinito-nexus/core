#!/usr/bin/env bash
set -euo pipefail

image="${1:?Usage: pull_with_retry.sh <image>}"
max_attempts="${MAX_ATTEMPTS:-7}"
retry_delay_seconds="${RETRY_DELAY_SECONDS:-20}"
attempt=1

while true; do
	echo "=== docker pull ${image} attempt ${attempt}/${max_attempts} ==="
	if docker pull "${image}"; then
		echo "Pulled ${image} on attempt ${attempt}/${max_attempts}."
		break
	fi

	if [[ "${attempt}" -ge "${max_attempts}" ]]; then
		echo "Failed to pull ${image} after ${max_attempts} attempts." >&2
		exit 1
	fi

	echo "Attempt ${attempt} failed. Retrying in ${retry_delay_seconds}s..."
	sleep "${retry_delay_seconds}"
	attempt=$((attempt + 1))
done
