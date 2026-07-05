#!/usr/bin/env bash
set -euo pipefail

: "${STACK:?STACK env var is required}"

is_completed_oneshot() {
	local ps
	ps=$(docker service ps --no-trunc \
		--format '{{.DesiredState}}|{{.CurrentState}}' "$1" 2>/dev/null) || return 1
	[ -n "$ps" ] || return 1
	awk -F'|' '
		{ d = $1; c = $2 }
		d ~ /Running/ || d ~ /Ready/ { pending = 1 }
		d ~ /Shutdown/ && c ~ /Complete/ { done_ok = 1 }
		END { exit (done_ok && !pending) ? 0 : 1 }
	' <<<"$ps"
}

not_running=""
while read -r name reps; do
	[ -n "$name" ] || continue
	if awk -v r="$reps" 'BEGIN { split(r, a, "/"); exit (a[1] == a[2]) ? 0 : 1 }'; then
		continue
	fi
	is_completed_oneshot "$name" && continue
	not_running="$not_running $name"
done < <(docker stack services --format '{{.Name}} {{.Replicas}}' "$STACK")

if [ -n "$not_running" ]; then
	echo "not converged:$not_running" >&2
	{
		for svc in $not_running; do
			echo "=== docker service ps --no-trunc ${svc} ==="
			docker service ps --no-trunc "$svc" 2>/dev/null || true
		done
		echo "=== journalctl -u docker (last 3 min) ==="
		journalctl -u docker --no-pager -n 100 --since "3 min ago" 2>/dev/null || echo "(journalctl -u docker unavailable)"
		echo "=== docker events (last 3 min) ==="
		timeout 5 docker events --since 3m --until 0s 2>/dev/null || echo "(docker events unavailable)"
	} >&2
	exit 1
fi
