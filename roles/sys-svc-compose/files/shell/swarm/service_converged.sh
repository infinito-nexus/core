#!/usr/bin/env bash
set -euo pipefail

: "${SERVICE:?SERVICE env var is required}"

state=$(timeout 15 container service inspect "$SERVICE" \
	--format '{{.UpdateStatus.State}}' 2>/dev/null) || state=""
case "$state" in
"" | "<no value>" | completed | rollback_completed) ;;
*) exit 1 ;;
esac

states=$(timeout 15 container service ps "$SERVICE" \
	--filter desired-state=running \
	--format '{{.CurrentState}}')
[ -n "$states" ] || exit 1
if printf '%s\n' "$states" | grep -qvE '^Running'; then
	exit 1
fi
