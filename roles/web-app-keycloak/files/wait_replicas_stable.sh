#!/usr/bin/env bash
set -euo pipefail

ok=0
n=0
while [ "$n" -lt 6 ]; do
	got="$(container service ls --filter name="${SVC}" --format '{{.Replicas}}' | head -1)"
	if [ "$got" = "${WANT}" ]; then
		ok=$((ok + 1))
		[ "$ok" -ge 3 ] && exit 0
	else
		ok=0
	fi
	n=$((n + 1))
	sleep 3
done
exit 1
