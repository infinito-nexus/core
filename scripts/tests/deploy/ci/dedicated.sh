#!/usr/bin/env bash
set -euo pipefail

# Deploy exactly ONE app on ONE distro against the same stack, with the
# matrix-aware sync + async passes co-located per variant.
#
# Flow:
#   1) Ensure compose stack is up (reuse if already running)
#   2) Init inventory once (ASYNC_ENABLED=false baked into host_vars).
#      For roles with `meta/variants.yml` this materialises one folder
#      per variant; otherwise a single unsuffixed folder.
#   3) Deploy with `--full-cycle`: per matrix round the dev wrapper runs
#      the sync deploy, then immediately the async re-deploy with
#      `-e ASYNC_ENABLED=true`, BEFORE moving to the next variant.
#      Inter-round cleanup runs only for apps whose variant changed.
#   4) Always remove stack so the next distro starts fresh.
#
# Required env:
#   INFINITO_DISTRO="arch|debian|ubuntu|fedora|centos"
#   INVENTORY_DIR="/path/to/inventory"
#
# Optional env:
#   PYTHON="python3"
#   VARIANT="<idx>"  pin to one matrix round (skips the rest)

PYTHON="${PYTHON:-python3}"

: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (e.g. arch)}"
: "${INVENTORY_DIR:?INVENTORY_DIR must be set}"
: "${INFINITO_DOCKER_VOLUME:?INFINITO_DOCKER_VOLUME must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

APPS=""

usage() {
	cat <<'EOF'
Usage:
  INFINITO_DISTRO=<distro> INVENTORY_DIR=<dir> INFINITO_DOCKER_VOLUME=<abs_path> \
    scripts/tests/deploy/ci/dedicated.sh \
    --apps <app_ids>
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--apps)
		APPS="${2:-}"
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
[[ -n "${APPS}" ]] || {
	echo "[ERROR] --apps is required" >&2
	usage
	exit 2
}

cd "${REPO_ROOT}"

echo "=== distro=${INFINITO_DISTRO} app=${APPS} (debug always on) ==="

cleanup() {
	rc=$?

	# Copy Playwright reports from the infinito container to the runner filesystem
	# BEFORE containers/volumes are destroyed, so GitHub Actions can upload them as artifacts.
	local _playwright_host_dir="/tmp/playwright-artifacts/${INFINITO_DISTRO}/${APPS}"
	mkdir -p "${_playwright_host_dir}"
	echo ">>> Copying Playwright artifacts from ${INFINITO_CONTAINER} to ${_playwright_host_dir}"
	docker cp "${INFINITO_CONTAINER}:/var/lib/infinito/logs/test-e2e-playwright/." \
		"${_playwright_host_dir}" 2>/dev/null || true

	echo ">>> Removing stack for distro ${INFINITO_DISTRO} (fresh start for next distro)"
	"${PYTHON}" -m cli.deploy.development down || true

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

	# 5) Remove ALL images and build cache.
	# Important for serial multi-distro CI runs on the same runner.
	docker image prune -af >/dev/null 2>&1 || true
	docker buildx prune -af >/dev/null 2>&1 || true
	docker builder prune -af >/dev/null 2>&1 || true

	# 6) Remove host-mounted Docker data dir (CI runner only)
	# IMPORTANT:
	# - In CI, Docker/DIND/buildx may create root-owned files under this directory.
	# - A plain 'rm -rf' can fail with "Permission denied" and poison the next distro run.
	# - Use sudo for a hard reset, then recreate the directory.
	if [[ -n "${INFINITO_DOCKER_VOLUME:-}" ]]; then
		if [[ "${INFINITO_DOCKER_VOLUME}" == /* ]]; then
			echo ">>> CI cleanup: wiping Docker root: ${INFINITO_DOCKER_VOLUME}"

			echo ">>> Pre-clean ownership/permissions (best-effort)"
			ls -ld "${INFINITO_DOCKER_VOLUME}" || true
			sudo ls -ld "${INFINITO_DOCKER_VOLUME}" || true

			echo ">>> Removing host docker volume dir: ${INFINITO_DOCKER_VOLUME}"
			sudo rm -rf "${INFINITO_DOCKER_VOLUME}" || true
			sudo mkdir -vp "${INFINITO_DOCKER_VOLUME}" || true

			# Optional: keep it writable for the runner user
			sudo chown -R "$(id -u):$(id -g)" "${INFINITO_DOCKER_VOLUME}" || true

			echo ">>> Post-clean ownership/permissions (best-effort)"
			ls -ld "${INFINITO_DOCKER_VOLUME}" || true
			sudo ls -ld "${INFINITO_DOCKER_VOLUME}" || true
		else
			echo "[WARN] INFINITO_DOCKER_VOLUME is not an absolute path: '${INFINITO_DOCKER_VOLUME}' (skipping)"
		fi
	fi

	# 7) Remove root-owned __pycache__ and .pyc files left by the privileged container.
	# Without this, the next actions/checkout fails with EACCES when trying to delete them.
	echo ">>> Removing root-owned Python bytecode from workspace"
	sudo find "${REPO_ROOT}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	sudo find "${REPO_ROOT}" -name "*.pyc" -delete 2>/dev/null || true

	echo ">>> Docker disk usage after HARD cleanup"
	docker system df || true
	echo ">>> HARD cleanup finished"
	return $rc
}
trap cleanup EXIT

echo ">>> Ensuring stack is up for distro ${INFINITO_DISTRO}"
# Always reconcile the stack to the requested distro.
# This avoids reusing a pre-started stack with a different INFINITO_DISTRO.
"${PYTHON}" -m cli.deploy.development up

deploy_args=(
	--apps "${APPS}"
	--inventory-dir "${INVENTORY_DIR}"
	--debug
)

echo ">>> DISK / DOCKER STATE BEFORE DEPLOY (distro=${INFINITO_DISTRO})"
df -h || true
docker system df || true
echo ">>> END STATE BEFORE DEPLOY"

echo ">>> init inventory (ASYNC_ENABLED=false baked into host_vars)"
"${PYTHON}" -m cli.deploy.development init \
	--apps "${APPS}" \
	--inventory-dir "${INVENTORY_DIR}" \
	--vars '{"ASYNC_ENABLED": false}'

# PASS 1 (sync) + PASS 2 (async) co-located per variant: the wrapper
# runs each round's deploy twice, second call with `-e ASYNC_ENABLED=true`
# overriding the host_var, BEFORE moving to the next variant. That keeps
# the async re-deploy targeting exactly the host state the matching sync
# deploy just produced and avoids the matrix-twice race the previous
# split passes had on multi-variant roles.
echo ">>> deploy (PASS 1 sync + PASS 2 async per variant, --full-cycle)"
"${PYTHON}" -m cli.deploy.development deploy "${deploy_args[@]}" --full-cycle

echo ">>> DISK / DOCKER STATE AFTER DEPLOY (before cleanup, distro=${INFINITO_DISTRO})"
df -h || true
docker system df || true
echo ">>> END STATE AFTER DEPLOY"
