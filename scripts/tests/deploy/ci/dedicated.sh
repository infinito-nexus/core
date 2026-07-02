#!/usr/bin/env bash
set -euo pipefail

# Deploy one app on one distro: bring the stack up, init the inventory (one folder
# per meta/variants.yml round), deploy --full-cycle (sync + async per variant), then
# always remove the stack so the next distro starts fresh.
#
# Required env:
#   INFINITO_DISTRO="arch|debian|ubuntu|fedora|centos"
#   INFINITO_INVENTORY_DIR="/path/to/inventory"
#
# Optional env:
#   PYTHON="python3"
#   variant="<csv>"  pin to one or more matrix rounds, e.g. "2" or "0,1,2"
#                    (the runner-split bundle from CI discovery); empty = all

: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (e.g. arch)}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR must be set}"
: "${INFINITO_DOCKER_VOLUME:?INFINITO_DOCKER_VOLUME must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

apps=""

usage() {
	cat <<'EOF'
Usage:
  INFINITO_DISTRO=<distro> INFINITO_INVENTORY_DIR=<dir> INFINITO_DOCKER_VOLUME=<abs_path> \
    scripts/tests/deploy/ci/dedicated.sh \  # nocheck: self-path-reference
    --apps <app_ids>
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--apps)
		apps="${2:-}"
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "[ERROR] Unknown argument: $1" >&2
		usage
		exit 2
		;;
	esac
done
[[ -n "${apps}" ]] || {
	echo "[ERROR] --apps is required" >&2
	usage
	exit 2
}

cd "${REPO_ROOT}"

echo "=== distro=${INFINITO_DISTRO} app=${apps} (debug always on) ==="

cleanup() {
	rc=$?

	# Copy Playwright reports from the infinito container to the runner filesystem
	# BEFORE containers/volumes are destroyed, so GitHub Actions can upload them as artifacts.
	local _playwright_host_dir="/tmp/playwright-artifacts/${INFINITO_DISTRO}/${apps}"
	mkdir -p "${_playwright_host_dir}"
	echo ">>> Copying Playwright artifacts from ${INFINITO_CONTAINER} to ${_playwright_host_dir}"
	docker cp "${INFINITO_CONTAINER}:/var/lib/infinito/logs/test-e2e-playwright/." \
		"${_playwright_host_dir}" 2>/dev/null || true

	if [[ -n "${ANSIBLE_LOG_PATH:-}" ]]; then
		echo ">>> Copying Ansible log from ${INFINITO_CONTAINER}:${ANSIBLE_LOG_PATH} to ${ANSIBLE_LOG_PATH}"
		docker cp "${INFINITO_CONTAINER}:${ANSIBLE_LOG_PATH}" "${ANSIBLE_LOG_PATH}" 2>/dev/null || true
	fi

	echo ">>> Removing stack for distro ${INFINITO_DISTRO} (fresh start for next distro)"
	"${PYTHON}" -m cli.administration.deploy.development down || true

	echo ">>> HARD cleanup (containers/volumes/networks/images/build-cache)"
	echo ">>> Docker disk usage before HARD cleanup"
	docker system df || true

	# 1) Remove containers belonging to this compose project only.
	# On shared self-hosted runners multiple projects run in parallel;
	# removing all containers would kill sibling jobs.
	_cleanup_project="${COMPOSE_PROJECT_NAME:-}"
	if [[ -n "${_cleanup_project}" ]]; then
		mapfile -t ids < <(docker ps -aq --filter "label=com.docker.compose.project=${_cleanup_project}" || true)
	else
		mapfile -t ids < <(docker ps -aq || true)
	fi
	if ((${#ids[@]} > 0)); then
		docker rm -f "${ids[@]}" >/dev/null 2>&1 || true
	fi

	# 2) Remove networks (except default ones)
	docker network prune -f >/dev/null 2>&1 || true

	# 3) Remove ALL volumes
	docker volume prune -f >/dev/null 2>&1 || true

	# 4) Optional: leftover stopped containers (usually redundant after rm -f)
	docker container prune -f >/dev/null 2>&1 || true

	# 5) Remove all images + build cache (frees disk on GitHub runners).
	# Skipped on self-hosted (INFINITO_PRESERVE_DOCKER_CACHE=true) to keep the cache warm.
	if [[ "${INFINITO_PRESERVE_DOCKER_CACHE}" != "true" ]]; then
		docker image prune -af >/dev/null 2>&1 || true
		docker buildx prune -af >/dev/null 2>&1 || true
		docker builder prune -af >/dev/null 2>&1 || true
	else
		# On self-hosted runners keep only the current CI image per distro.
		# Removes all older ci-<hash> tags so disk usage stays flat across runs.
		if [[ -n "${INFINITO_IMAGE:-}" ]]; then
			_image_repo="${INFINITO_IMAGE%%:*}"
			mapfile -t _old_ci_images < <(
				docker images --format "{{.Repository}}:{{.Tag}}" |
					grep "^${_image_repo}:ci-" |
					grep -vxF "${INFINITO_IMAGE}" ||
					true
			)
			if ((${#_old_ci_images[@]} > 0)); then
				echo ">>> Pruning ${#_old_ci_images[@]} stale CI image(s) for ${_image_repo}"
				docker rmi "${_old_ci_images[@]}" >/dev/null 2>&1 || true
			fi
		fi
	fi

	# 6) Reset the host-mounted Docker data dir (sudo: the container leaves root-owned
	# files that would break the next checkout). Skipped when preserving the cache.
	if [[ "${INFINITO_PRESERVE_DOCKER_CACHE}" == "true" ]]; then
		echo ">>> INFINITO_PRESERVE_DOCKER_CACHE=true — keeping Docker root for next distro: ${INFINITO_DOCKER_VOLUME}"
	elif [[ -n "${INFINITO_DOCKER_VOLUME:-}" ]]; then
		if [[ "${INFINITO_DOCKER_VOLUME}" == /* ]]; then
			echo ">>> CI cleanup: wiping Docker root: ${INFINITO_DOCKER_VOLUME}"

			echo ">>> Pre-clean ownership/permissions (best-effort)"
			ls -ld "${INFINITO_DOCKER_VOLUME}" || true

			echo ">>> Removing host docker volume dir: ${INFINITO_DOCKER_VOLUME}"
			sudo rm -rf "${INFINITO_DOCKER_VOLUME}" || true
			sudo mkdir -vp "${INFINITO_DOCKER_VOLUME}" || true

			# Optional: keep it writable for the runner user
			sudo chown -R "$(id -u):$(id -g)" "${INFINITO_DOCKER_VOLUME}" || true

			echo ">>> Post-clean ownership/permissions (best-effort)"
			ls -ld "${INFINITO_DOCKER_VOLUME}" || true
		else
			echo "[WARN] INFINITO_DOCKER_VOLUME is not an absolute path: '${INFINITO_DOCKER_VOLUME}' (skipping)"
		fi
	fi

	# 7) Remove root-owned __pycache__/.pyc (else the next checkout fails with EACCES).
	echo ">>> Removing root-owned Python bytecode from workspace"
	sudo find "${REPO_ROOT}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	sudo find "${REPO_ROOT}" -name "*.pyc" -delete 2>/dev/null || true

	echo ">>> Docker disk usage after HARD cleanup"
	docker system df || true
	echo ">>> HARD cleanup finished"
	return $rc
}
trap cleanup EXIT

# Wipe stale inner-Docker volumes/containers before `up` (fresh credentials), keeping
# image layers for cache. If disk >70%, wipe the whole volume to reclaim space.
if [[ "${INFINITO_PRESERVE_DOCKER_CACHE}" == "true" ]]; then
	_disk_pct=$(df --output=pcent / | tail -1 | tr -d ' %')
	if [[ "${_disk_pct}" -ge 70 && -n "${INFINITO_DOCKER_VOLUME:-}" && "${INFINITO_DOCKER_VOLUME}" == /* ]]; then
		echo ">>> Disk at ${_disk_pct}% — wiping full inner-Docker volume to reclaim space: ${INFINITO_DOCKER_VOLUME}"
		sudo rm -rf "${INFINITO_DOCKER_VOLUME}" || true
		sudo mkdir -p "${INFINITO_DOCKER_VOLUME}" || true
		sudo chown -R "$(id -u):$(id -g)" "${INFINITO_DOCKER_VOLUME}" || true
	else
		echo ">>> Wiping inner-Docker volumes and container state: ${INFINITO_DOCKER_VOLUME}"
		sudo rm -rf "${INFINITO_DOCKER_VOLUME}/volumes" "${INFINITO_DOCKER_VOLUME}/containers" || true
	fi
fi

echo ">>> Ensuring stack is up for distro ${INFINITO_DISTRO}"
# Always reconcile the stack to the requested distro.
# This avoids reusing a pre-started stack with a different INFINITO_DISTRO.
"${PYTHON}" -m cli.administration.deploy.development up

# Pre-install the CA trust wrapper: if the bind-mount target is missing, Docker
# creates it as a directory (every exec then exits rc=126). sys-ca-selfsigned
# overwrites this stub with the real version later.
_up_container="${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set (run make dotenv)}"
docker exec "${_up_container}" install -m 755 \
	/opt/src/infinito/roles/sys-ca-selfsigned/files/with-ca-trust.sh \
	/usr/bin/ca-trust-wrapper 2>/dev/null || true

deploy_args=(
	--apps "${apps}"
	--inventory-dir "${INFINITO_INVENTORY_DIR}"
	--debug
)

echo ">>> DISK / DOCKER STATE BEFORE DEPLOY (distro=${INFINITO_DISTRO})"
df -h || true
docker system df || true
echo ">>> END STATE BEFORE DEPLOY"

_init_args=(
	--apps "${apps}"
	--inventory-dir "${INFINITO_INVENTORY_DIR}"
)
if [[ "${INFINITO_PRESERVE_DOCKER_CACHE}" == "true" ]]; then
	_init_args+=(--force-storage-constrained false)
fi

if [[ "${INFINITO_TIMEOUT_MULTIPLIER}" -gt 1 ]]; then
	echo ">>> Scaling Ansible retries by ${INFINITO_TIMEOUT_MULTIPLIER}x (slow hardware detected)"
	docker exec \
		-e "INFINITO_TIMEOUT_MULTIPLIER=${INFINITO_TIMEOUT_MULTIPLIER}" \
		-e "INFINITO_REPO_ROOT=/opt/src/infinito" \
		"${_up_container}" \
		bash /opt/src/infinito/scripts/tests/deploy/ci/multiply-timeouts.sh
fi

echo ">>> init inventory (ASYNC_ENABLED=false baked into host_vars)"
"${PYTHON}" -m cli.administration.deploy.development init \
	"${_init_args[@]}" \
	--vars '{"ASYNC_ENABLED": false}'

# Per variant: sync deploy, then async re-deploy (-e ASYNC_ENABLED=true) before the
# next variant, so async targets the exact host state sync just produced.
echo ">>> deploy (PASS 1 sync + PASS 2 async per variant, --full-cycle)"
"${PYTHON}" -m cli.administration.deploy.development deploy "${deploy_args[@]}" --full-cycle

echo ">>> DISK / DOCKER STATE AFTER DEPLOY (before cleanup, distro=${INFINITO_DISTRO})"
df -h || true
docker system df || true
echo ">>> END STATE AFTER DEPLOY"
