#!/usr/bin/env bash
# SPOT for the cluster bring-up, one CI step: host-side compose build + up (node
# image layered on the distro's infinito image, so python + ansible + the CLI are
# baked -- no per-node .deb bootstrap), then every node concern (systemd wait,
# IPs, lab DNS, repo unpack) via compose/swarm/playbook.yml over the docker
# connection. Host-side pre-clean here is only the bind-mount dir + leftover
# containers; stale root-owned NFS writes are wiped in-node by the play (this
# often non-root act runner cannot delete them).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "${SCRIPT_DIR}/../utils/topology/base.sh"
set +a

# shellcheck source=scripts/meta/env/load.sh
source "${SCRIPT_DIR}/../../../../../scripts/meta/env/load.sh"

: "${RUNNER_TEMP:?}" "${APP_ID:?}" "${INFINITO_DOMAIN:?}"

if command -v apt-get >/dev/null 2>&1; then
	if [ "$(id -u)" -eq 0 ]; then apt-get update -qq || true; else sudo -E apt-get update -qq || true; fi
fi

bash "${SCRIPT_DIR}/../utils/unmount_nfs_mounts.sh" "${NFS_SERVER}" >/dev/null 2>&1 || true
for node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}" "${BACKUP_NODE}"; do
	docker rm -f "${node}" >/dev/null 2>&1 || true
done
docker volume rm "${SWARM_NAME}_nfs-export" >/dev/null 2>&1 || true

REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
if [ -z "${INFINITO_IMAGE:-}" ]; then
	INFINITO_IMAGE="$(bash "${REPO_ROOT}/scripts/meta/resolve/image/local.sh"):${INFINITO_IMAGE_TAG:?}"
	export INFINITO_IMAGE
	if ! docker image inspect "${INFINITO_IMAGE}" >/dev/null 2>&1; then
		echo "==> building local infinito image ${INFINITO_IMAGE} for distro ${INFINITO_DISTRO}"
		make -C "${REPO_ROOT}" build
	fi
fi

COMPOSE_FILE="${SCRIPT_DIR}/../../../../../compose/swarm/compose.yml"
COMPOSE_ARGS=(-f "${COMPOSE_FILE}")
CACHE_FRONTEND="infinito-package-cache-frontend"
CACHE_NET=""
if docker inspect "${CACHE_FRONTEND}" >/dev/null 2>&1; then
	CACHE_NET="$(docker inspect "${CACHE_FRONTEND}" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | head -n1)"
	echo "==> package-cache detected on ${CACHE_NET}; wiring swarm nodes to it"
	COMPOSE_ARGS+=(-f "${SCRIPT_DIR}/../../../../../compose/swarm/cache.override.yml")
fi

build_attempts=3
for attempt in $(seq 1 "${build_attempts}"); do
	docker compose "${COMPOSE_ARGS[@]}" -p "${SWARM_NAME}" --profile drill build && break
	if [ "${attempt}" -eq "${build_attempts}" ]; then
		echo "FAILURE: node image build failed after ${build_attempts} attempts" >&2
		exit 1
	fi
	sleep $((attempt * 5))
done

docker compose "${COMPOSE_ARGS[@]}" -p "${SWARM_NAME}" --profile drill up -d

if [ -n "${CACHE_NET}" ]; then
	for node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}" "${BACKUP_NODE}"; do
		docker network connect "${CACHE_NET}" "${node}" >/dev/null 2>&1 || true
	done
fi

ansible-playbook \
	-i "${MGR},${WRK1},${WRK2},${NFS_SERVER},${BACKUP_NODE}," \
	-c docker \
	"${SCRIPT_DIR}/../../../../../compose/swarm/playbook.yml"
