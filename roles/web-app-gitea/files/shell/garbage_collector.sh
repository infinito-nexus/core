#!/bin/bash
# @param $1 mode: routine | pressure
#
# Required environment:
#   GARBAGE_COLLECTOR_ADDRESS                  container address, resolved by the sys-ctl-cln-apps dispatcher
#   GARBAGE_COLLECTOR_APP_TIMEOUT              seconds the in-container find may run, set by the dispatcher
#   GITEA_GARBAGE_COLLECTOR_MINUTES_ROUTINE    minimum age in minutes of a leftover the routine pass removes
#   GITEA_GARBAGE_COLLECTOR_MINUTES_PRESSURE   minimum age in minutes of a leftover the pressure pass removes
set -euo pipefail

case "${1:-}" in
routine) minutes="${GITEA_GARBAGE_COLLECTOR_MINUTES_ROUTINE:?}" ;;
pressure) minutes="${GITEA_GARBAGE_COLLECTOR_MINUTES_PRESSURE:?}" ;;
*)
	echo "usage: $0 routine|pressure" >&2
	exit 64
	;;
esac

# shellcheck disable=SC2016  # $1 and $2 expand in the inner sh -c, not here
container exec -u git "${GARBAGE_COLLECTOR_ADDRESS:?}" timeout "${GARBAGE_COLLECTOR_APP_TIMEOUT:?}" sh -c '
	[ -d "$1" ] || { echo "$1 does not exist yet, nothing to clean"; exit 0; }
	exec find "$1" -type f -path "*/objects/pack/tmp_*" -mmin "+$2" -print -exec rm -f -- {} +
' garbage-collector /data/git/repositories "${minutes}"
