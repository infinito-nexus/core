#!/bin/bash
# @param $1 mode handed to every garbage collector script: routine | pressure
#
# Required environment:
#   GARBAGE_COLLECTOR_MANIFEST_DIR  one <application_id>/ per deployed role, holding garbage_collector.sh and garbage_collector.env
#   GARBAGE_COLLECTOR_APP_TIMEOUT   seconds a single application's garbage collector may run, on the host and inside its container
#   BIN_RESOLVE_CONTAINER_ID        swarm task to container id resolver
#
# Read from each garbage_collector.env:
#   DEPLOYMENT_MODE                'swarm' or 'compose' as the role resolved it
#   GARBAGE_COLLECTOR_CONTAINER    compose container name
#   GARBAGE_COLLECTOR_STACK        swarm stack name
#   GARBAGE_COLLECTOR_SERVICE_KEY  swarm service key
#
# Exported to each garbage_collector.sh:
#   GARBAGE_COLLECTOR_ADDRESS       target for `container exec`
#   GARBAGE_COLLECTOR_APP_TIMEOUT   budget every in-container command runs under
#
# Exit codes:
#   0   every application collected, or skipped because none of its containers runs on this node;
#       a service without any running container is skipped with a warning
#   1   at least one application failed; each one is named on stderr
#   64  unknown mode or a GARBAGE_COLLECTOR_APP_TIMEOUT that is no positive number of seconds
set -uo pipefail

mode="${1:-}"
case "${mode}" in
routine | pressure) ;;
*)
	echo "usage: $0 routine|pressure" >&2
	exit 64
	;;
esac

: "${GARBAGE_COLLECTOR_MANIFEST_DIR:?}" "${GARBAGE_COLLECTOR_APP_TIMEOUT:?}"
[[ ${GARBAGE_COLLECTOR_APP_TIMEOUT} =~ ^[1-9][0-9]*$ ]] || {
	echo "GARBAGE_COLLECTOR_APP_TIMEOUT must be a positive number of seconds, got '${GARBAGE_COLLECTOR_APP_TIMEOUT}'" >&2
	exit 64
}

resolve_address() {
	if [ "${DEPLOYMENT_MODE}" = "swarm" ]; then
		"${BIN_RESOLVE_CONTAINER_ID:?}" "${GARBAGE_COLLECTOR_STACK}" "${GARBAGE_COLLECTOR_SERVICE_KEY}"
		return
	fi
	local running
	running="$(container ps --quiet --filter "name=^/?${GARBAGE_COLLECTOR_CONTAINER}\$" --filter status=running)" || return 70
	[ -n "${running}" ] || return 65
	printf '%s' "${GARBAGE_COLLECTOR_CONTAINER}"
}

collect() {
	local app_dir="$1"
	local app="${app_dir##*/}"
	(
		set -a
		# shellcheck source=/dev/null
		. "${app_dir}/garbage_collector.env" || exit 78
		set +a
		case "${DEPLOYMENT_MODE:-}" in
		swarm) required=(GARBAGE_COLLECTOR_STACK GARBAGE_COLLECTOR_SERVICE_KEY) ;;
		compose) required=(GARBAGE_COLLECTOR_CONTAINER) ;;
		*)
			echo "garbage_collector.env of ${app} sets DEPLOYMENT_MODE '${DEPLOYMENT_MODE:-}', not swarm or compose" >&2
			exit 78
			;;
		esac
		for key in "${required[@]}"; do
			[ -n "${!key:-}" ] || {
				echo "garbage_collector.env of ${app} leaves ${key} empty" >&2
				exit 78
			}
		done
		address="$(resolve_address)"
		rc=$?
		case "${rc}" in
		0) ;;
		64 | 66)
			echo "skipped: no running container on this node (exit ${rc})"
			exit 0
			;;
		65)
			echo "warning: skipped, the service has no running container at all (exit 65)" >&2
			exit 0
			;;
		*)
			echo "container resolution failed (exit ${rc})" >&2
			exit "${rc}"
			;;
		esac
		export GARBAGE_COLLECTOR_ADDRESS="${address}"
		exec timeout --kill-after=60 "${GARBAGE_COLLECTOR_APP_TIMEOUT}" "${app_dir}/garbage_collector.sh" "${mode}"
	)
}

[ -d "${GARBAGE_COLLECTOR_MANIFEST_DIR}" ] || {
	echo "no garbage collector manifest directory ${GARBAGE_COLLECTOR_MANIFEST_DIR}"
	exit 0
}

exec 9>"${GARBAGE_COLLECTOR_MANIFEST_DIR%/}/.lock"
flock 9

failed=()
shopt -s nullglob
for app_dir in "${GARBAGE_COLLECTOR_MANIFEST_DIR%/}"/*/; do
	app_dir="${app_dir%/}"
	app="${app_dir##*/}"
	echo "${app}: garbage collector ${mode}"
	if collect "${app_dir}" 2>&1 | sed -u "s|^|${app}: |"; then
		echo "${app}: done"
	else
		echo "${app}: FAILED" >&2
		failed+=("${app}")
	fi
done

if [ "${#failed[@]}" -gt 0 ]; then
	echo "garbage collector failed for: ${failed[*]}" >&2
	exit 1
fi
exit 0
