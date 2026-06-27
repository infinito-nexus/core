#!/usr/bin/env bash
set -euo pipefail

: "${node:?node= must be set, e.g. node=swarm-mgr-01}"

if ! docker inspect --format '{{.State.Running}}' "${node}" 2>/dev/null | grep -q '^true$'; then
	echo "ERROR: container '${node}' is not running. Run \`make act-swarm-zombie app=<id>\` first." >&2
	exit 1
fi

repo_root="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "${repo_root}"

# Mirror 04_bootstrap_nodes.sh: tar the working-tree's modified+untracked files into the
# node's frozen bootstrap copy at /opt/infinito-nexus (the nodes are not bind-mounted, so a
# repo edit is otherwise invisible on the node).
git ls-files -z -m -o --exclude-standard |
	tar --null -cf - -T - |
	docker exec -i "${node}" tar -C /opt/infinito-nexus -xpf -
