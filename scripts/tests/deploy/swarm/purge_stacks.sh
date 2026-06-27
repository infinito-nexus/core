#!/usr/bin/env bash
set -euo pipefail

# Per-round swarm purge for the variant matrix: remove each prior-round stack
# and clear its NFS-backed volumes so the next round boots from clean state.
# Driven by cli.administration.deploy.swarm.matrix between rounds; env `apps` is
# the plan-constant purge_set (comma/space separated application ids).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
# shellcheck source=scripts/tests/deploy/swarm/00_topology.sh
source "${SCRIPT_DIR}/00_topology.sh"

: "${apps:?apps is not set (e.g. apps=web-app-keycloak,svc-db-postgres)}"
: "${MGR:?MGR is not set; 00_topology.sh must define it}"

# NFS volumes bind to ${DIR_VAR_LIB}/<docker_name> on every node (the shared NFS
# mount), so clearing them on the manager wipes the round's shared state.
DIR_VAR_LIB="$(python3 -c "import yaml,sys;print(yaml.safe_load(open(sys.argv[1]))['DIR_VAR_LIB'])" \
	"${REPO_ROOT}/group_vars/all/05_paths.yml")"

read -r -a app_list <<<"${apps//,/ }"

for app_id in "${app_list[@]}"; do
	[ -n "${app_id}" ] || continue

	# Reuse _context.sh's per-app derivation: line 1 = entity (stack) name,
	# remaining lines = nfs docker_names from the role's meta/volumes.yml.
	mapfile -t ctx < <(
		APP_ID="${app_id}" bash -c \
			"source '${SCRIPT_DIR}/_context.sh' >/dev/null 2>&1; printf '%s\n' \"\${ENTITY}\"; printf '%s' \"\${NFS_VOLUMES}\""
	)
	entity="${ctx[0]:-}"
	[ -n "${entity}" ] || continue

	echo "=== purge_stacks: removing stack '${entity}' (app ${app_id}) ==="
	docker exec "${MGR}" docker stack rm "${entity}" >/dev/null 2>&1 || true

	# stack rm is async; wait until the tasks are gone before clearing the NFS
	# volume, else the next deploy races a still-mounted writer.
	for _ in $(seq 1 60); do
		remaining="$(docker exec "${MGR}" docker stack ps "${entity}" \
			--format '{{.Name}}' 2>/dev/null | grep -c . || true)"
		[ "${remaining}" -eq 0 ] && break
		sleep 2
	done

	for vol in "${ctx[@]:1}"; do
		[ -n "${vol}" ] || continue
		echo "=== purge_stacks: clearing NFS volume '${vol}' (${DIR_VAR_LIB}/${vol}) ==="
		# Tolerate an NFS teardown race: a worker still releasing the bind mount
		# leaves .nfsXXXX silly-rename files (ENOTEMPTY). Warn, do not abort the
		# whole matrix.
		docker exec "${MGR}" sh -c \
			"rm -rf '${DIR_VAR_LIB}/${vol}'/* '${DIR_VAR_LIB}/${vol}'/.[!.]* 2>/dev/null; mkdir -p '${DIR_VAR_LIB}/${vol}'" ||
			echo "warn: clear of NFS volume '${vol}' hit a teardown race, continuing"
	done
done

# Named volumes (e.g. postgres_data) survive `docker stack rm` and are NOT the
# nfs-bind kind cleared above; once their stacks are gone they are unattached,
# so prune them on every node so the next round's variant re-imports into fresh
# DB state instead of reusing the prior round's database.
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	docker exec "${node}" docker volume prune -f >/dev/null 2>&1 || true
done
