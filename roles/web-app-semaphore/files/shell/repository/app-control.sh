#!/usr/bin/env bash
# Args:
#   $1  stop or start
#   $2  an application id, or all for every application under app control
#
# Env (the project environment and the inventory Semaphore runs the template with):
#   APP_CONTROL_TARGETS      space-separated user@host the action runs on
#   APP_CONTROL_KNOWN_HOSTS  known_hosts lines pinning the host key of every target
#   SSH_AUTH_SOCK            agent holding the app-control key of the inventory
set -euo pipefail

SCRIPT="app-control.sh"
# shellcheck source=SCRIPTDIR/lib.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib.sh"

refuse_arguments 2 "$@"
case "$1" in
stop | start) ;;
*)
	echo "app-control.sh: unknown action '$1'" >&2
	exit 2
	;;
esac
if [[ ! "$2" =~ ^(all|[a-z0-9]+(-[a-z0-9]+)*)$ ]]; then
	echo "app-control.sh: '$2' is no application id" >&2
	exit 2
fi
: "${APP_CONTROL_TARGETS:?the project environment names no target}"
: "${APP_CONTROL_KNOWN_HOSTS:?the project environment pins no host key}"
: "${SSH_AUTH_SOCK:?the inventory carries no SSH key}"

known_hosts="$(mktemp)"
trap 'rm -f "${known_hosts}"' EXIT
printf '%s\n' "${APP_CONTROL_KNOWN_HOSTS}" >"${known_hosts}"

read -r -a targets <<<"${APP_CONTROL_TARGETS}"
for target in "${targets[@]}"; do
	echo "=== app-control $1 $2 on ${target} ==="
	ssh -T \
		-o BatchMode=yes \
		-o ConnectTimeout=30 \
		-o StrictHostKeyChecking=yes \
		-o GlobalKnownHostsFile=/dev/null \
		-o "UserKnownHostsFile=${known_hosts}" \
		"${target}" app-control "$1" "$2"
done
