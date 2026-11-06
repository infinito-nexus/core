#!/bin/bash
# @param $1 mode: routine | pressure
#
# Required environment:
#   GARBAGE_COLLECTOR_ADDRESS                  container address, resolved by the sys-ctl-cln-apps dispatcher
#   GARBAGE_COLLECTOR_APP_TIMEOUT              seconds the in-container tootctl may run, set by the dispatcher
#   MASTODON_GARBAGE_COLLECTOR_DAYS_ROUTINE    age in days of cached remote media the routine pass removes
#   MASTODON_GARBAGE_COLLECTOR_DAYS_PRESSURE   age in days of cached remote media the pressure pass removes
set -euo pipefail

case "${1:-}" in
routine) days="${MASTODON_GARBAGE_COLLECTOR_DAYS_ROUTINE:?}" ;;
pressure) days="${MASTODON_GARBAGE_COLLECTOR_DAYS_PRESSURE:?}" ;;
*)
	echo "usage: $0 routine|pressure" >&2
	exit 64
	;;
esac

[[ ${days} =~ ^[1-9][0-9]*$ ]] || {
	echo "media cache age must be a whole number of days, at least 1, got '${days}'" >&2
	exit 64
}

container exec -u root "${GARBAGE_COLLECTOR_ADDRESS:?}" timeout "${GARBAGE_COLLECTOR_APP_TIMEOUT:?}" bin/tootctl media remove --days="${days}"
