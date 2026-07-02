#!/usr/bin/env bash
set -euo pipefail

: "${node:?node= must be set, e.g. node=swarm-mgr-01}"

if ! docker inspect --format '{{.State.Running}}' "${node}" 2>/dev/null | grep -q '^true$'; then
	echo "ERROR: container '${node}' is not running. Run \`make swarm-zombie app=<id>\` first." >&2
	exit 1
fi

repo_root="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "${repo_root}"

git ls-files -z -m -o --exclude-standard |
	tar --null -cf - -T - |
	docker exec -i "${node}" tar -C /opt/infinito-nexus -xpf -
