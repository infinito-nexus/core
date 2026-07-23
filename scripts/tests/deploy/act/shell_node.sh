#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "$(dirname "$0")/../swarm/utils/topology/base.sh"

node="${node:-${MGR}}"

if ! docker inspect --format '{{.State.Running}}' "${node}" 2>/dev/null | grep -q '^true$'; then
	echo "ERROR: container '${node}' is not running." >&2
	echo "Available swarm-test containers (if any):" >&2
	docker ps --format '  {{.Names}}\t{{.Status}}' |
		grep -E 'swarm-|nfs-server' >&2 ||
		echo "  (none — run \`make swarm-zombie app=<id>\` first)" >&2
	exit 1
fi

exec docker exec -it "${node}" bash
