#!/bin/bash
# @param $1 mode: routine | pressure
#
# Required environment:
#   GC_ADDRESS                  container address, resolved by the sys-ctl-cln-apps dispatcher
#   GC_APP_TIMEOUT              seconds the in-container find may run, set by the dispatcher
#   GITEA_GC_MINUTES_ROUTINE    minimum age in minutes of a leftover the routine pass removes
#   GITEA_GC_MINUTES_PRESSURE   minimum age in minutes of a leftover the pressure pass removes
set -euo pipefail

case "${1:-}" in
routine) minutes="${GITEA_GC_MINUTES_ROUTINE:?}" ;;
pressure) minutes="${GITEA_GC_MINUTES_PRESSURE:?}" ;;
*)
	echo "usage: $0 routine|pressure" >&2
	exit 64
	;;
esac

container exec -u git "${GC_ADDRESS:?}" timeout "${GC_APP_TIMEOUT:?}" sh -c '
	[ -d "$1" ] || { echo "$1 does not exist yet, nothing to clean"; exit 0; }
	exec find "$1" -type f -path "*/objects/pack/tmp_*" -mmin "+$2" -print -exec rm -f -- {} +
' gc /data/git/repositories "${minutes}"
