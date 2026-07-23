#!/usr/bin/env bash
set -euo pipefail

: "${STACK:?STACK env var is required}"

is_completed_oneshot() {
	local ps
	ps=$(timeout 15 docker service ps --no-trunc \
		--format '{{.Name}}|{{.DesiredState}}|{{.CurrentState}}' "$1" 2>/dev/null) || return 1
	[ -n "$ps" ] || return 1
	awk -F'|' '
		!seen[$1]++ {
			if ($2 ~ /Running/ || $2 ~ /Ready/) pending = 1
			else if ($2 ~ /Shutdown/ && $3 ~ /Complete/) done_ok = 1
			else bad = 1
		}
		END { exit (done_ok && !pending && !bad) ? 0 : 1 }
	' <<<"$ps"
}

if ! services=$(timeout 15 docker stack services --format '{{.Name}} {{.Replicas}}' "$STACK"); then
	echo "not converged: docker stack services failed or timed out for ${STACK}" >&2
	exit 1
fi

not_running=""
while read -r name reps; do
	[ -n "$name" ] || continue
	if awk -v r="$reps" 'BEGIN { split(r, a, "/"); exit (a[1] == a[2]) ? 0 : 1 }'; then
		continue
	fi
	is_completed_oneshot "$name" && continue
	not_running="$not_running $name"
done <<<"$services"

if [ -n "$not_running" ]; then
	echo "not converged:$not_running" >&2
	exit 1
fi
