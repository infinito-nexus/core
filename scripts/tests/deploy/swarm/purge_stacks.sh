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

DIR_VAR_LIB="$(python3 -c "import yaml,sys;print(yaml.safe_load(open(sys.argv[1]))['DIR_VAR_LIB'])" \
	"${REPO_ROOT}/group_vars/all/05_paths.yml")"

read -r -a app_list <<<"${apps//,/ }"

for app_id in "${app_list[@]}"; do
	[ -n "${app_id}" ] || continue

	mapfile -t ctx < <(
		APP_ID="${app_id}" bash -c \
			"source '${SCRIPT_DIR}/_context.sh' >/dev/null 2>&1; printf '%s\n' \"\${ENTITY}\"; printf '%s' \"\${NFS_VOLUMES}\""
	)
	entity="${ctx[0]:-}"
	[ -n "${entity}" ] || continue

	echo "=== purge_stacks: removing stack '${entity}' (app ${app_id}) ==="
	docker exec "${MGR}" docker stack rm "${entity}" >/dev/null 2>&1 || true

	for _ in $(seq 1 60); do
		remaining="$(docker exec "${MGR}" docker stack ps "${entity}" \
			--format '{{.Name}}' 2>/dev/null | grep -c . || true)"
		[ "${remaining}" -eq 0 ] && break
		sleep 2
	done

	for vol in "${ctx[@]:1}"; do
		[ -n "${vol}" ] || continue
		echo "=== purge_stacks: clearing NFS volume '${vol}' (${DIR_VAR_LIB}/${vol}) ==="
		docker exec "${MGR}" sh -c \
			"rm -rf '${DIR_VAR_LIB}/${vol}'/* '${DIR_VAR_LIB}/${vol}'/.[!.]* 2>/dev/null; mkdir -p '${DIR_VAR_LIB}/${vol}'" ||
			echo "warn: clear of NFS volume '${vol}' hit a teardown race, continuing"
	done
done

for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	docker exec "${node}" docker volume prune -a -f >/dev/null 2>&1 || true
done
