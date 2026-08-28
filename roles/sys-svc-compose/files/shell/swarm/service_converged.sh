#!/usr/bin/env bash
set -euo pipefail

: "${SERVICE:?SERVICE env var is required}"

fail() {
	echo "${SERVICE}: $1" >&2
	exit 1
}

report_tasks() {
	local ps rows
	if ! ps=$(timeout 15 container service ps "$SERVICE" --no-trunc \
		--format '{{.Name}} {{.Node}} {{.DesiredState}} {{.CurrentState}} error={{.Error}}' 2>&1); then
		printf '%s: service ps failed: %s\n' "${SERVICE}" "${ps}" >&2
		return 0
	fi
	rows="$(printf '%s\n' "${ps}" | awk '!/error=$/ && n++ < 10')"
	[ -n "${rows}" ] || return 0
	printf '%s\n' "${rows}" >&2
}

give_up() {
	echo "${SERVICE}: $1" >&2
	report_tasks
	exit 2
}

report_failed_tasks() {
	echo "${SERVICE}: $1" >&2
	report_tasks
	exit 1
}

state=$(timeout 15 container service inspect "$SERVICE" \
	--format '{{.UpdateStatus.State}}' 2>/dev/null) || state=""
case "$state" in
"" | "<no value>" | completed) ;;
rollback_started | rollback_completed) give_up "update was rolled back (UpdateStatus.State=${state}); the running spec is the previous one, not the desired one" ;;
paused | rollback_paused) give_up "update latched (UpdateStatus.State=${state}); it cannot leave this state on its own" ;;
*) fail "update in progress (UpdateStatus.State=${state})" ;;
esac

states=$(timeout 15 container service ps "$SERVICE" \
	--filter desired-state=running \
	--format '{{.CurrentState}}') || fail "service ps failed or timed out"
if [ -z "$states" ]; then
	fail "no task carries desired-state=running"
fi
if grep -qvE '^Running' <<<"$states"; then
	report_failed_tasks "tasks not running yet"
fi
