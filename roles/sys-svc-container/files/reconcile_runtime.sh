#!/usr/bin/env bash
#
# Reap container scopes that outlived a containerd restart, then resync dockerd.
#
# Prints RECONCILED when it acted, UNCHANGED when the runtime was consistent.
set -euo pipefail

STOP_TIMEOUT=120
RESTART_TIMEOUT=120
ACTIVE_TIMEOUT=60

# Param: $1 unit name
# Prints the unit's ActiveEnterTimestampMonotonic, or nothing for a unit systemd
# does not know, which answers 0.
started() {
	local value
	value="$(systemctl show --property=ActiveEnterTimestampMonotonic --value "$1")"
	case "${value}" in
	'' | 0) return 0 ;;
	*) printf '%s' "${value}" ;;
	esac
}

containerd_started="$(started containerd.service)"
if [ -z "${containerd_started}" ]; then
	echo "UNCHANGED: no running containerd to compare against"
	exit 0
fi

scopes="$(systemctl list-units 'docker-*.scope' --state=active --no-legend --plain | awk '{print $1}')"

orphans=()
while read -r scope; do
	[ -n "${scope}" ] || continue
	scope_started="$(started "${scope}")"
	[ -n "${scope_started}" ] || continue
	if [ "${scope_started}" -lt "${containerd_started}" ]; then
		orphans+=("${scope}")
	fi
done <<<"${scopes}"

if [ "${#orphans[@]}" -eq 0 ]; then
	echo "UNCHANGED: containerd restarted but left no orphaned container scope"
	exit 0
fi

reaped=()
for scope in "${orphans[@]}"; do
	rc=0
	timeout "${STOP_TIMEOUT}" systemctl stop "${scope}" || rc=$?
	if [ "${rc}" -eq 5 ]; then
		continue
	fi
	if [ "${rc}" -ne 0 ]; then
		echo "FAILURE: could not stop ${scope} (rc ${rc})" >&2
		exit 1
	fi
	if [ "$(systemctl is-active "${scope}" || true)" = "active" ]; then
		echo "FAILURE: ${scope} is still active after being stopped" >&2
		exit 1
	fi
	reaped+=("${scope}")
done

if [ "${#reaped[@]}" -gt 0 ]; then
	timeout "${RESTART_TIMEOUT}" systemctl restart docker.service || true
	for _ in $(seq "${ACTIVE_TIMEOUT}"); do
		[ "$(systemctl is-active docker.service || true)" = "active" ] && break
		sleep 1
	done
	if [ "$(systemctl is-active docker.service || true)" != "active" ]; then
		echo "FAILURE: docker.service is not running after the reap; this node cannot start containers" >&2
		exit 1
	fi
fi

if [ "${#reaped[@]}" -eq 0 ]; then
	echo "UNCHANGED: every orphaned scope had already gone away"
	exit 0
fi

echo "RECONCILED: ${#reaped[@]} orphaned container scope(s) reaped, dockerd restarted"
