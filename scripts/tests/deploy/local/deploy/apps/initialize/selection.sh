#!/usr/bin/env bash
set -euo pipefail

# Local app test without teardown/cleanup.
# Usage:
#   scripts/tests/deploy/local/deploy/apps/initialize/selection.sh <app-id>  # nocheck: self-path-reference
#
# Environment variables:
#   INFINITO_DISTRO   arch|debian|ubuntu|fedora|centos (default from scripts/meta/env/load.sh)
#   INFINITO_INVENTORY_DIR     target inventory dir (default from scripts/meta/env/load.sh)
#   INFINITO_LIMIT_HOST        host limit (default: localhost)
#   INFINITO_DEBUG    true|false (default: true)
#
# Examples:
#   scripts/tests/deploy/local/deploy/apps/initialize/selection.sh web-app-mailu  # nocheck: self-path-reference
#   INFINITO_DISTRO=arch INFINITO_DEBUG=false scripts/tests/deploy/local/deploy/apps/initialize/selection.sh web-app-nextcloud  # nocheck: self-path-reference

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../../.." && pwd)"

# shellcheck source=scripts/tests/deploy/local/utils/lib.sh
source "${SCRIPT_DIR}/../../../utils/lib.sh"
# shellcheck source=scripts/tests/deploy/local/utils/cache-retry.sh
source "${SCRIPT_DIR}/../../../utils/cache-retry.sh"

cd "${REPO_ROOT}"

if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
else
	echo "ERROR: missing scripts/meta/env/load.sh" >&2
	exit 2
fi

: "${PYTHON:=python3}"

usage() {
	cat <<'EOF'
Usage:
  initialize/selection.sh <app-id>

ENV:
  INFINITO_DISTRO=<arch|debian|ubuntu|fedora|centos>
  INFINITO_INVENTORY_DIR=<path>
  INFINITO_LIMIT_HOST=<host-pattern>
  INFINITO_DEBUG=<true|false>
  -h, --help
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -eq 0 ]]; then
	usage
	exit 0
fi

apps="${1:-}"
shift

if [[ -z "${apps}" ]]; then
	echo "ERROR: app-id is required" >&2
	usage
	exit 2
fi

if [[ $# -gt 0 ]]; then
	echo "ERROR: unknown argument(s): $*" >&2
	echo "Pass config via ENV (INFINITO_DISTRO, INFINITO_INVENTORY_DIR, INFINITO_LIMIT_HOST, INFINITO_DEBUG)." >&2
	usage
	exit 2
fi

# INFINITO_DISTRO is set by scripts/meta/env/load.sh (single SPOT,
# defaults to debian) — no local fallback here.
INFINITO_INVENTORY_DIR="${INFINITO_INVENTORY_DIR:-}"

if [[ -z "${INFINITO_INVENTORY_DIR}" ]]; then
	echo "ERROR: INFINITO_INVENTORY_DIR is empty after loading scripts/meta/env/load.sh" >&2
	exit 2
fi

case "${INFINITO_DISTRO}" in
arch | debian | ubuntu | fedora | centos) ;;
*)
	echo "ERROR: invalid distro '${INFINITO_DISTRO}'" >&2
	exit 2
	;;
esac

INFINITO_DEBUG="$(normalize_bool_or_default "${INFINITO_DEBUG:-}" true INFINITO_DEBUG)"

echo "=== local app test (no cleanup) ==="
echo "app ids       = ${apps}"
echo "distro        = ${INFINITO_DISTRO}"
echo "inventory_dir = ${INFINITO_INVENTORY_DIR}"
echo "limit         = ${INFINITO_LIMIT_HOST}"
echo "debug         = ${INFINITO_DEBUG}"
echo

echo ">>> Ensuring development stack is up (when-down)"
"${PYTHON}" -m cli.administration.deploy.development up \
	--when-down

echo ">>> Running entry.sh bootstrap inside container"
"${PYTHON}" -m cli.administration.deploy.development exec \
	-- bash "${INFINITO_SRC_DIR}/scripts/tests/deploy/local/utils/entry-bootstrap.sh"

echo ">>> Creating inventory for app '${apps}'"
# RUNTIME MUST be `dev` here: the host process running this script lives
# OUTSIDE the development compose stack, so `detect_runtime()` falls back
# to "host". Without an explicit override the matrix-init step would bake
# `RUNTIME=host` into host_vars and the Playwright E2E gate
# (RUNTIME in [dev, act, github]) would never fire — kept-deploys would
# silently skip the test stage. Mirrors apps/reinstall/selection.sh.
"${PYTHON}" -m cli.administration.deploy.development init \
	--apps "${apps}" \
	--inventory-dir "${INFINITO_INVENTORY_DIR}" \
	--vars '{"ASYNC_ENABLED": false, "RUNTIME": "dev"}'

deploy_cmd=(
	"${PYTHON}" -m cli.administration.deploy.development deploy
	--apps "${apps}"
	--inventory-dir "${INFINITO_INVENTORY_DIR}"
)

if [[ "${INFINITO_DEBUG}" == "true" ]]; then
	deploy_cmd+=(--debug)
fi

# NOTE: --skip-cleanup keeps cleanup routines disabled during this local test run.
deploy_cmd+=(-- --skip-backup --skip-cleanup --limit "${INFINITO_LIMIT_HOST}")

echo ">>> Deploying app '${apps}'"
deploy_with_cache_retry "deploy-${apps//[^A-Za-z0-9._-]/-}-kept" -- "${deploy_cmd[@]}"

echo
echo "✅ Finished. Stack and inventory remain on disk (no teardown)."
