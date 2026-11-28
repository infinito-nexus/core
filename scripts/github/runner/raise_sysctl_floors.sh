#!/usr/bin/env bash
# Usage: raise_sysctl_floors.sh VARS_FILE
#   VARS_FILE  role vars file whose RUNNER_SYSCTL_PARAMETERS maps each kernel key to its numeric floor
set -euo pipefail

VARS_FILE="${1:?VARS_FILE is required - name the role vars file that holds RUNNER_SYSCTL_PARAMETERS at the call site}"

floors="$(awk '
	/^RUNNER_SYSCTL_PARAMETERS:/ { inside = 1; next }
	inside && /^[^[:space:]]/ { exit }
	inside && /^[[:space:]]+[^[:space:]#]/ {
		line = $0
		sub(/^[[:space:]]+/, "", line)
		key = line
		sub(/:.*/, "", key)
		value = line
		sub(/^[^:]*:[[:space:]]*/, "", value)
		gsub(/["\047]/, "", value)
		print key, value
	}
' "${VARS_FILE}")"

if [ -z "${floors}" ]; then
	echo "::error::RUNNER_SYSCTL_PARAMETERS in ${VARS_FILE} is empty" >&2
	exit 1
fi

while read -r key floor; do
	if ! [[ "${floor}" =~ ^[0-9]+$ ]]; then
		echo "::error::${key} floor must be a non-negative integer, got '${floor}'" >&2
		exit 1
	fi
	current="$(sysctl -n "${key}")"
	if ! [[ "${current}" =~ ^[0-9]+$ ]]; then
		echo "::error::${key} reads '${current}', not a single integer" >&2
		exit 1
	fi
	if [ "${current}" -ge "${floor}" ]; then
		echo "${key}=${current} already meets the floor ${floor}"
		continue
	fi
	sudo sysctl -w "${key}=${floor}" >/dev/null
	echo "${key} raised ${current} -> ${floor}"
done <<<"${floors}"
