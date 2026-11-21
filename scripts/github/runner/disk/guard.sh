#!/usr/bin/env bash
# Usage: disk/guard.sh WATCHED_PATH MIN_FREE_GB INTERVAL_SECONDS -- COMMAND [ARG...]
#   WATCHED_PATH      a path on the volume that holds the Actions worker's own logs
#   MIN_FREE_GB       free GB on WATCHED_PATH below which COMMAND is stopped
#   INTERVAL_SECONDS  seconds between two free-space samples, the first at start;
#                     the end of COMMAND and signals still land within a second
#   COMMAND           the guarded step; it runs in a process group of its own
# Exit: COMMAND's exit code, 75 when the floor stopped it, 2 on a usage error.
# The Actions worker dies without a job log once its volume is full (#1377), so
# COMMAND is stopped above the floor: the step log, the disk pressure report and
# every always() step after it survive.
set -euo pipefail

if [ "$#" -lt 5 ] || [ "$4" != "--" ]; then
	echo "::error::usage: disk/guard.sh WATCHED_PATH MIN_FREE_GB INTERVAL_SECONDS -- COMMAND [ARG...]" >&2
	exit 2
fi
WATCHED_PATH="$1"
MIN_FREE_GB="$2"
INTERVAL_SECONDS="$3"
shift 4
COMMAND_TEXT="$*"

if ! [[ "${MIN_FREE_GB}" =~ ^[1-9][0-9]*$ && "${INTERVAL_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
	echo "::error::MIN_FREE_GB and INTERVAL_SECONDS must be positive integers, got '${MIN_FREE_GB}' and '${INTERVAL_SECONDS}'" >&2
	exit 2
fi
if [ ! -d "${WATCHED_PATH}" ]; then
	echo "::error::WATCHED_PATH '${WATCHED_PATH}' is not a directory" >&2
	exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT="${HERE}/pressure_report.sh"

setsid "$@" &
pid=$!

# Param: $1 signal for every process of COMMAND's group; a group already gone is fine
signal_group() {
	kill -s "$1" -- "-${pid}" 2>/dev/null || [ "$?" -eq 1 ]
}

# Param: $1 exit code of the guard once COMMAND's process group is gone
stop() {
	trap - INT TERM
	signal_group TERM
	status=0
	wait "${pid}" || status=$?
	signal_group KILL
	echo "disk/guard.sh: '${COMMAND_TEXT}' ended with ${status} after the guard stopped it"
	exit "$1"
}

trap 'stop 130' INT
trap 'stop 143' TERM

since_sample="${INTERVAL_SECONDS}"
while kill -0 "${pid}" 2>/dev/null; do
	if [ "${since_sample}" -ge "${INTERVAL_SECONDS}" ]; then
		since_sample=0
		if ! free_gb="$(df --output=avail -B1G "${WATCHED_PATH}" | tail -n1 | tr -d ' ')" || ! [[ "${free_gb}" =~ ^[0-9]+$ ]]; then
			echo "::error::disk/guard.sh stops '${COMMAND_TEXT}': df could not measure ${WATCHED_PATH} (got '${free_gb:-}')"
			stop 75
		fi
		if [ "${free_gb}" -lt "${MIN_FREE_GB}" ]; then
			echo "::error::disk/guard.sh stops '${COMMAND_TEXT}': ${WATCHED_PATH} has ${free_gb}G free, below the ${MIN_FREE_GB}G floor that keeps the Actions worker's own log writable"
			if ! "${REPORT}" DISK-GUARD; then
				echo "::warning::disk/pressure_report.sh failed while ${WATCHED_PATH} had ${free_gb}G free"
			fi
			stop 75
		fi
	fi
	sleep 1
	since_sample=$((since_sample + 1))
done

status=0
wait "${pid}" || status=$?
exit "${status}"
