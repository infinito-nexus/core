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
#   INFINITO_INVENTORY_DIR="/path/to/inventory"
#
# Optional env:
#   PYTHON="python3"
#   variant="<csv>"  pin to one or more matrix rounds, e.g. "2" or "0,1,2"
#                    (the runner-split bundle from CI discovery); empty = all

PYTHON="${PYTHON:-python3}"

: "${INFINITO_DISTRO:?INFINITO_DISTRO must be set (e.g. arch)}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR must be set}"
: "${INFINITO_DOCKER_VOLUME:?INFINITO_DOCKER_VOLUME must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
# shellcheck source=/dev/null
source <(grep -E '^INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR=' "${REPO_ROOT}/.env")

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

	local _playwright_host_dir="/tmp/playwright-artifacts/${INFINITO_DISTRO}/${apps}"
	mkdir -p "${_playwright_host_dir}"
	echo ">>> Copying Playwright artifacts from ${INFINITO_CONTAINER} to ${_playwright_host_dir}"
	docker cp "${INFINITO_CONTAINER}:${INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR}/." \
		"${_playwright_host_dir}" 2>/dev/null || true

	local _inv_parent
	_inv_parent="$(dirname "${INFINITO_INVENTORY_DIR}")"
	echo ">>> Copying generated inventory from ${INFINITO_CONTAINER} to host ${_inv_parent}"
	mkdir -p "${_inv_parent}"
	docker cp "${INFINITO_CONTAINER}:${_inv_parent}/." "${_inv_parent}/" 2>/dev/null || true

	echo ">>> Removing stack for distro ${INFINITO_DISTRO} (fresh start for next distro)"
	"${PYTHON}" -m cli.administration.deploy.development down || true

	echo ">>> HARD cleanup (containers/volumes/networks/images/build-cache)"
	echo ">>> Docker disk usage before HARD cleanup"
	docker system df || true

	mapfile -t ids < <(docker ps -aq || true)
	if ((${#ids[@]} > 0)); then
		docker rm -f "${ids[@]}" >/dev/null 2>&1 || true
	fi

	docker network prune -f >/dev/null 2>&1 || true
	docker volume prune -f >/dev/null 2>&1 || true
	docker container prune -f >/dev/null 2>&1 || true

	docker image prune -af >/dev/null 2>&1 || true
	docker buildx prune -af >/dev/null 2>&1 || true
	docker builder prune -af >/dev/null 2>&1 || true

	if [[ -n "${INFINITO_DOCKER_VOLUME:-}" ]]; then
		if [[ "${INFINITO_DOCKER_VOLUME}" == /* ]]; then
			echo ">>> CI cleanup: wiping Docker root: ${INFINITO_DOCKER_VOLUME}"

			echo ">>> Pre-clean ownership/permissions (best-effort)"
			ls -ld "${INFINITO_DOCKER_VOLUME}" || true
			sudo ls -ld "${INFINITO_DOCKER_VOLUME}" || true

			echo ">>> Removing host docker volume dir: ${INFINITO_DOCKER_VOLUME}"
			sudo rm -rf "${INFINITO_DOCKER_VOLUME}" || true
			sudo mkdir -vp "${INFINITO_DOCKER_VOLUME}" || true

			sudo chown -R "$(id -u):$(id -g)" "${INFINITO_DOCKER_VOLUME}" || true

			echo ">>> Post-clean ownership/permissions (best-effort)"
			ls -ld "${INFINITO_DOCKER_VOLUME}" || true
			sudo ls -ld "${INFINITO_DOCKER_VOLUME}" || true
		else
			echo "[WARN] INFINITO_DOCKER_VOLUME is not an absolute path: '${INFINITO_DOCKER_VOLUME}' (skipping)"
		fi
	fi

	echo ">>> Docker disk usage after HARD cleanup"
	docker system df || true
	echo ">>> HARD cleanup finished"
	return $rc
}
trap cleanup EXIT

echo ">>> Ensuring stack is up for distro ${INFINITO_DISTRO}"
"${PYTHON}" -m cli.administration.deploy.development up

deploy_args=(
	--apps "${apps}"
	--inventory-dir "${INFINITO_INVENTORY_DIR}"
	--debug
)

echo ">>> DISK / DOCKER STATE BEFORE DEPLOY (distro=${INFINITO_DISTRO})"
df -h || true
docker system df || true
echo ">>> END STATE BEFORE DEPLOY"

echo ">>> init inventory (ASYNC_ENABLED=false baked into host_vars)"
"${PYTHON}" -m cli.administration.deploy.development init \
	--apps "${apps}" \
	--inventory-dir "${INFINITO_INVENTORY_DIR}" \
	--vars '{"ASYNC_ENABLED": false}'

echo ">>> deploy (PASS 1 sync + PASS 2 async per variant, --full-cycle)"
"${PYTHON}" -m cli.administration.deploy.development deploy "${deploy_args[@]}" --full-cycle

echo ">>> DISK / DOCKER STATE AFTER DEPLOY (before cleanup, distro=${INFINITO_DISTRO})"
df -h || true
docker system df || true
echo ">>> END STATE AFTER DEPLOY"
