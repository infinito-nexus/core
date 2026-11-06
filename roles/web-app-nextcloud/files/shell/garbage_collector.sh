#!/bin/bash
# @param $1 mode: routine | pressure
#
# Required environment:
#   GARBAGE_COLLECTOR_ADDRESS          container address, resolved by the sys-ctl-cln-apps dispatcher
#   GARBAGE_COLLECTOR_APP_TIMEOUT      seconds each in-container occ command may run, set by the dispatcher
#   NEXTCLOUD_GARBAGE_COLLECTOR_USER   user occ runs as inside the container
#   NEXTCLOUD_GARBAGE_COLLECTOR_OCC    path of occ inside the container
set -euo pipefail

case "${1:-}" in
routine) commands=(trashbin:expire) ;;
pressure) commands=(trashbin:expire preview:cleanup) ;;
*)
	echo "usage: $0 routine|pressure" >&2
	exit 64
	;;
esac

for command in "${commands[@]}"; do
	container exec -u "${NEXTCLOUD_GARBAGE_COLLECTOR_USER:?}" "${GARBAGE_COLLECTOR_ADDRESS:?}" timeout "${GARBAGE_COLLECTOR_APP_TIMEOUT:?}" "${NEXTCLOUD_GARBAGE_COLLECTOR_OCC:?}" "${command}"
done
