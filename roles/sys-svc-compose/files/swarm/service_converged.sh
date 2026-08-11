#!/usr/bin/env bash
set -euo pipefail

: "${SERVICE:?SERVICE env var is required}"

fail() {
	echo "${SERVICE}: $1" >&2
	exit 1
}

give_up() {
	echo "${SERVICE}: $1" >&2
	timeout 15 container service ps "$SERVICE" --no-trunc \
		--format '{{.Name}} {{.Node}} {{.DesiredState}} {{.CurrentState}} error={{.Error}}' 2>&1 |
		awk '!/error=$/' | head -10 >&2 || true
	exit 2
}

report_failed_tasks() {
	echo "${SERVICE}: $1" >&2
	timeout 15 container service ps "$SERVICE" --no-trunc \
		--format '{{.Name}} {{.Node}} {{.DesiredState}} {{.CurrentState}} error={{.Error}}' 2>&1 |
		awk '!/error=$/' | head -10 >&2 || true
	exit 1
}

state=$(timeout 15 container service inspect "$SERVICE" \
	--format '{{.UpdateStatus.State}}' 2>/dev/null) || state=""
case "$state" in
"" | "<no value>" | completed | rollback_completed) ;;
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
