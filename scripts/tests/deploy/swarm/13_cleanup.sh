#!/usr/bin/env bash
set +e

if [ "${INFINITO_KEEP_SWARM_NODES}" = "true" ]; then
	echo "INFINITO_KEEP_SWARM_NODES=true -> preserving swarm cluster for post-mortem inspection."
	echo "Inspect: make act-swarm-exec node=swarm-mgr-01 cmd='docker service ls'"
	echo "Release: make act-swarm-down"
	exit 0
fi

# shellcheck source=scripts/tests/deploy/swarm/topology.sh
. "$(dirname "$0")/topology.sh"

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
DIR_VAR_LIB="$(python3 -c "import yaml,sys;print(yaml.safe_load(open(sys.argv[1]))['DIR_VAR_LIB'])" \
	"${REPO_ROOT}/group_vars/all/05_paths.yml")"

if mountpoint -q "${DIR_VAR_LIB}" 2>/dev/null; then
	umount -lf "${DIR_VAR_LIB}" || true
fi

docker rm -f "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}" 2>/dev/null
docker network rm "${SWARM_LAB_NETWORK}" 2>/dev/null
exit 0
