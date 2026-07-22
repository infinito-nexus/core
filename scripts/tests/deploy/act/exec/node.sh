#!/usr/bin/env bash
set -euo pipefail

: "${node:?node= must be set, e.g. node=swarm-mgr-01}"
: "${cmd:?cmd= must be set, e.g. cmd='docker service ls'}"

if ! docker inspect --format '{{.State.Running}}' "${node}" 2>/dev/null | grep -q '^true$'; then
	echo "ERROR: container '${node}' is not running." >&2
	echo "Available swarm-test containers (if any):" >&2
	docker ps --format '  {{.Names}}\t{{.Status}}' |
		grep -E 'swarm-|nfs-server' >&2 ||
		echo "  (none — run \`make swarm-zombie app=<id>\` first)" >&2
	exit 1
fi

docker exec -i "${node}" bash --noprofile --norc -c "${cmd}"
