#!/usr/bin/env bash
set -euo pipefail

: "${STACK:?STACK env var is required}"
: "${FATAL_GRACE:?FATAL_GRACE env var is required}"

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

report_tasks() {
	local ps rows
	if ! ps=$(timeout 15 docker service ps --no-trunc \
		--format '{{.Name}} desired={{.DesiredState}} current={{.CurrentState}} error={{.Error}}' "$1" 2>&1); then
		printf '  %s: docker service ps failed: %s\n' "$1" "$ps" >&2
		return 0
	fi
	rows="$(printf '%s\n' "$ps" | head -10)"
	[ -n "${rows}" ] || return 0
	printf '%s\n' "${rows}" | sed 's/^/  /' >&2
	report_task_states "$1"
}

# Exception: `docker service ps` renders CurrentState as prose ("Preparing 3 minutes ago"), which
# cannot distinguish an image still extracting from a task idling on something else.
report_task_states() {
	local ids inspect
	if ! ids=$(timeout 15 docker service ps --no-trunc --format '{{.ID}}' "$1" 2>/dev/null); then
		return 0
	fi
	ids="$(printf '%s\n' "${ids}" | head -10 | tr '\n' ' ')"
	[ -n "${ids// /}" ] || return 0
	# shellcheck disable=SC2086
	if ! inspect=$(timeout 15 docker inspect --type task ${ids} \
		--format '{{.ID}} state={{.Status.State}} since={{.Status.Timestamp}} msg={{.Status.Message}}' 2>&1); then
		printf '  %s: task state dump failed: %s\n' "$1" "${inspect}" >&2
		return 0
	fi
	[ -n "${inspect}" ] || return 0
	printf '%s\n' "${inspect}" | sed 's/^/    /' >&2
}

churned_past_grace() {
	local now updated
	now=$(date +%s)
	updated=$(timeout 15 docker service inspect \
		--format '{{.UpdatedAt.Unix}}' "$1" 2>/dev/null) || return 1
	case "$updated" in
	'' | *[!0-9]*) return 1 ;;
	esac
	[ "$((now - updated))" -ge "$FATAL_GRACE" ]
}

has_fatal_task() {
	local ps grace=0
	churned_past_grace "$1" && grace=1
	ps=$(timeout 15 docker service ps --no-trunc \
		--format '{{.Name}}|{{.CurrentState}}|{{.Error}}' "$1" 2>/dev/null) || return 1
	[ -n "$ps" ] || return 1
	awk -F'|' -v grace="$grace" '
		{
			if (ended[$1]) next
			newest = !seen[$1]++
			if ($3 == "") { if (!newest) ended[$1] = 1; next }
			if (newest && $2 ~ /^(Rejected|Pending)/) fatal = 1
			if (++errs[$1] >= 3 && grace) fatal = 1
		}
		END { exit fatal ? 0 : 1 }
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
	fatal=0
	for svc in $not_running; do
		report_tasks "$svc"
		if has_fatal_task "$svc"; then
			echo "stuck: $svc" >&2
			fatal=1
		fi
	done
	if [ "$fatal" -ne 0 ]; then
		exit 2
	fi
	exit 1
fi
